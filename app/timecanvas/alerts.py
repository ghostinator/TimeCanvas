"""Alerts. Every minute: evaluate conditions, open an alert after two consecutive confirmations, notify (Teams Power Automate webhook and/or SMTP email),
remind while it stays open, and say so when it recovers. Runs in its own unit so it still fires when capture/health/web die.
Secrets (webhook URL, SMTP password, heartbeat URL) live in /var/lib/timecanvas/alerts.json (0600), typed in the dashboard and never shown back."""
import ipaddress, json, logging, os, re, smtplib, socket, ssl, subprocess, sys, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import archive, capture, config as cfgmod, db

log = logging.getLogger("timecanvas.alerts")
TS = "%Y-%m-%dT%H:%M:%S.%fZ"
SECRETS = os.environ.get("TC_ALERT_SECRETS", "/var/lib/timecanvas/alerts.json")
CERT = os.environ.get("TC_CERT", "/etc/timecanvas/certificates/timecanvas.crt")
WEBHOOK_SUFFIXES = (".logic.azure.com", ".powerplatform.com", ".webhook.office.com", ".office.com")
UA = "TimeCanvas-alerts/1.0"   # Cloudflare (error 1010) and similar WAFs reject Python's default User-Agent
SERVICES = ("ustreamer.service", "web.service", "render-worker.service", "capture.timer", "health.timer")

RULES = {   # key: (label, what it means)
    "camera_offline": ("Camera offline", "the streamer reports the camera is gone"),
    "capture_stale": ("No new photos", "capture is expected but no good photo arrived (any cause other than the camera being offline)"),
    "disk": ("Disk space", "the media disk passed the warning or critical level"),
    "archive": ("OneDrive archive", "the last archive run failed"),
    "service": ("Services", "a TimeCanvas service or timer is not running, or the health check stopped"),
    "cert": ("HTTPS certificate", "the certificate expires in under 14 days"),
}
DEFAULTS = {"alerts_enabled": "1", "alert_stale_minutes": "10", "alert_offline_minutes": "3", "alert_remind_hours": "6",
            "alert_teams_on": "0", "alert_email_on": "0", "alert_email_method": "postal", "alert_postal_url": "", "alert_smtp_host": "", "alert_smtp_port": "587", "alert_smtp_security": "starttls",
            "alert_smtp_user": "", "alert_mail_from": "", "alert_mail_to": "", **{f"alert_on_{k}": "1" for k in RULES}}
RANGES = {"alert_stale_minutes": (3, 1440), "alert_offline_minutes": (1, 1440), "alert_remind_hours": (1, 72), "alert_smtp_port": (1, 65535)}


def get_settings(c):
    return {k: db.get_setting(c, k, d) for k, d in DEFAULTS.items()}


def put(c, k, v):
    c.execute("INSERT INTO settings(key,value,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc", (k, v, db.utcnow()))


# ---------- secrets ----------
def load_secrets():
    try:
        with open(SECRETS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_secrets(updates):
    """Merge updates (None/'' value = delete) and write atomically with mode 0600."""
    cur = load_secrets()
    for k, v in updates.items():
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    tmp = SECRETS + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cur, f)
    os.replace(tmp, SECRETS)


def valid_webhook(u):
    """Only HTTPS Power Automate / Teams workflow hosts, no credentials in the URL, default port."""
    try:
        p = urlparse(u)
    except ValueError:
        return False
    h = (p.hostname or "").lower()
    return (p.scheme == "https" and not p.username and p.port in (None, 443) and len(u) <= 2000 and any(h.endswith(s) for s in WEBHOOK_SUFFIXES))


def valid_public_https(u, maxlen=500):
    """https URL to a public host NAME (no IP literal, no internal-looking suffix), default port, no credentials."""
    try:
        p = urlparse(u)
    except ValueError:
        return False
    h = (p.hostname or "")
    return p.scheme == "https" and not p.username and p.port in (None, 443) and len(u) <= maxlen and "." in h and not re.fullmatch(r"[\d.]+|[0-9a-f:]+", h) and not h.endswith((".local", ".internal", ".lan"))


def valid_heartbeat(u):
    """http(s) URL for a heartbeat/push monitor (healthchecks.io, Uptime Kuma on the tailnet, ...). Private and tailnet addresses are fine;
    loopback, link-local (cloud metadata), multicast and unspecified addresses are not. No credentials in the URL."""
    try:
        p = urlparse(u); port = p.port
    except ValueError:
        return False
    h = p.hostname or ""
    if p.scheme not in ("http", "https") or p.username or len(u) > 500 or not re.fullmatch(r"[A-Za-z0-9.:\-_\[\]]{1,253}", h) or h.lower() in ("localhost", "localhost.localdomain"):
        return False
    try:
        ip = ipaddress.ip_address(h)
        return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved)
    except ValueError:
        return not h.endswith(".localhost")


def valid_email(a):
    return bool(re.fullmatch(r"[^@\s,;<>]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,}", a or ""))


# ---------- conditions ----------
def _ts(s):
    return datetime.strptime(s, TS).replace(tzinfo=timezone.utc)


def _status(c):
    try:
        return json.loads(db.get_setting(c, "status") or "{}")
    except ValueError:
        return {}


def capture_expected(c, at, tz):
    if db.get_setting(c, "capture_enabled", "1") != "1":
        return False
    return capture.active_session(c, at, tz)[1]


def cert_days(path=None):
    try:
        out = subprocess.run(["openssl", "x509", "-in", path or CERT, "-noout", "-enddate"], capture_output=True, text=True, timeout=10).stdout
        end = datetime.strptime(out.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return (end - datetime.now(timezone.utc)).total_seconds() / 86400
    except Exception:
        return None


def service_states():
    out = {}
    for u in SERVICES:
        try:
            out[u] = subprocess.run(["systemctl", "is-active", f"timecanvas-{u}"], capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
        except Exception:
            out[u] = "unknown"
    return out


def ago(td):
    m = int(td.total_seconds() // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h {m % 60} min" if m < 2880 else f"{m // 1440} days"


def evaluate(c, cfg, s, now, services=service_states, certdays=cert_days):
    """{rule key: (severity, title, detail)} for conditions that are active now (rules switched off are never active)."""
    tz = cfgmod.effective(cfg, c)["timezone"]; z = ZoneInfo(tz); out = {}
    on = lambda k: s[f"alert_on_{k}"] == "1"
    st = _status(c)
    stale_m, off_m = int(s["alert_stale_minutes"]), int(s["alert_offline_minutes"])
    # camera offline: the streamer says so, for at least off_m minutes
    offline_active = False
    if st.get("camera_online") is False and "streamer_error" not in st:
        ev = c.execute("SELECT ts_utc FROM health_events WHERE source='camera' AND message='camera offline' ORDER BY id DESC LIMIT 1").fetchone()
        on_ev = c.execute("SELECT ts_utc FROM health_events WHERE source='camera' AND message='camera online' ORDER BY id DESC LIMIT 1").fetchone()
        since = _ts(ev[0]) if ev and (not on_ev or ev[0] > on_ev[0]) else _ts(st["ts_utc"]) if st.get("ts_utc") else now
        if now - since >= timedelta(minutes=off_m):
            offline_active = True
            if on("camera_offline"):
                last_ok = c.execute("SELECT ts_utc FROM capture_events WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
                out["camera_offline"] = ("critical", "Camera offline", f"The camera has been offline for {ago(now - since)} (since {since.astimezone(z):%a %H:%M}). "
                                         + (f"Last good photo: {_ts(last_ok[0]).astimezone(z):%a %H:%M}." if last_ok else "No photo has been captured yet.") + " Check the USB cable/repeater.")
    # no good photo although capture is expected (skipped while the streamer says the camera is offline: that alert owns the situation)
    offline_now = st.get("camera_online") is False and "streamer_error" not in st
    if on("capture_stale") and not offline_now and capture_expected(c, now, tz) and capture_expected(c, now - timedelta(minutes=stale_m), tz):
        cutoff = (now - timedelta(minutes=stale_m)).strftime(TS)
        recent_ok = c.execute("SELECT 1 FROM capture_events WHERE status='ok' AND ts_utc>=? LIMIT 1", (cutoff,)).fetchone()
        if not recent_ok:
            last_ok = c.execute("SELECT ts_utc FROM capture_events WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
            latest = c.execute("SELECT ts_utc,status,detail FROM capture_events ORDER BY id DESC LIMIT 1").fetchone()
            why = f"Latest attempt {_ts(latest[0]).astimezone(z):%H:%M}: {latest[1]}{' - ' + latest[2] if latest[2] else ''}." if latest else "Capture has not run at all."
            out["capture_stale"] = ("critical", "No new photos", f"No good photo for {stale_m}+ minutes"
                                    + (f" (last: {_ts(last_ok[0]).astimezone(z):%a %H:%M})" if last_ok else "") + f". {why}")
    # disk
    st_cfg = cfgmod.effective(cfg, c)["storage"]
    pct = st.get("disk_pct")
    if on("disk") and pct is not None and pct >= st_cfg["disk_warning_percent"]:
        crit = pct >= st_cfg["disk_critical_percent"]
        out["disk"] = ("critical" if crit else "warning", "Disk full" if crit else "Disk filling up",
                       f"The media disk is {pct}% used" + (" and capture has stopped." if crit else f" (warning at {st_cfg['disk_warning_percent']}%)."))
    # archive
    ast = json.loads(db.get_setting(c, "archive_status") or "{}")
    if on("archive") and archive.get(c)["enabled"] and ast and ast.get("ok") is False:
        out["archive"] = ("warning", "OneDrive archive failed", ast.get("msg", "")[:300])
    # services / health check
    if on("service"):
        bad = [f"{u} is {v}" for u, v in services().items() if v != "active"]
        if st.get("ts_utc") and now - _ts(st["ts_utc"]) > timedelta(minutes=3):
            bad.append(f"the health check has not reported for {ago(now - _ts(st['ts_utc']))}")
        if bad:
            out["service"] = ("critical", "Service problem", "; ".join(bad) + ".")
    # certificate
    d = certdays() if on("cert") else None
    if d is not None and d < 14:
        out["cert"] = ("critical" if d < 3 else "warning", "HTTPS certificate expiring", f"The dashboard certificate expires in {max(0, int(d))} days. Check timecanvas-tailscale-cert.")
    return out


# ---------- delivery ----------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _scrub(text, secrets=()):
    """Turn an HTTP error body into a short one-line hint without ever repeating a secret."""
    t = re.sub(r"<[^>]+>", " ", text or ""); t = re.sub(r"\s+", " ", t).strip()
    for sec in secrets:
        for part in {sec, *(re.findall(r"[A-Za-z0-9_%-]{12,}", sec or ""))}:
            if part: t = t.replace(part, "***")
    return t[:140]


def _http_error(ex, what, secrets=()):
    try:
        body = ex.read(400).decode(errors="replace")
    except Exception:
        body = ""
    hint = _scrub(body, secrets)
    return RuntimeError(f"{what} answered HTTP {ex.code}" + (f": {hint}" if hint else ""))


def ping_heartbeat(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=10) as r:
            r.read(200); return r.status
    except urllib.error.HTTPError as ex:
        raise _http_error(ex, "heartbeat URL", (url,))


def card(msg, host):
    color = {"critical": "Attention", "warning": "Warning", "ok": "Good", "info": "Accent"}.get(msg["severity"], "Default")
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": [
            {"type": "TextBlock", "text": msg["title"], "weight": "Bolder", "size": "Medium", "color": color, "wrap": True},
            {"type": "TextBlock", "text": msg["detail"], "wrap": True},
            {"type": "FactSet", "facts": [{"title": "Host", "value": host}, {"title": "When", "value": msg["when"]}, {"title": "Event", "value": msg["event"]}]}]}}]}


def send_teams(msg, secrets=None, host=None):
    url = (secrets or load_secrets()).get("teams_webhook")
    if not url or not valid_webhook(url):
        raise RuntimeError("no valid Teams webhook configured")
    req = urllib.request.Request(url, data=json.dumps(card(msg, host or socket.gethostname())).encode(), headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=15) as r:
            if r.status >= 300:
                raise RuntimeError(f"webhook answered HTTP {r.status}")
    except urllib.error.HTTPError as ex:
        raise _http_error(ex, "the Teams webhook", (url,))


def send_postal(msg, s, secrets=None, host=None):
    """Postal (https://postalserver.io) HTTP API: POST /api/v1/send/message with the server API key in X-Server-API-Key."""
    key = (secrets or load_secrets()).get("postal_api_key")
    to = [a.strip() for a in s["alert_mail_to"].split(",") if a.strip()]
    base = s["alert_postal_url"].rstrip("/")
    if not (key and valid_public_https(base) and s["alert_mail_from"] and to):
        raise RuntimeError("Postal is not fully configured (server URL, API key, from, to)")
    body = {"to": to, "from": s["alert_mail_from"], "subject": f"[TimeCanvas] {msg['event'].upper()}: {msg['title']}",
            "plain_body": f"{msg['title']}\n\n{msg['detail']}\n\nHost: {host or socket.gethostname()}\nWhen: {msg['when']}\nEvent: {msg['event']}\n"}
    req = urllib.request.Request(base + "/api/v1/send/message", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Server-API-Key": key, "User-Agent": UA})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=20) as r:
            res = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as ex:
        raise _http_error(ex, "Postal", (key,))
    if res.get("status") != "success":   # Postal reports many errors as HTTP 200 with status "error"
        d = res.get("data") or {}
        raise RuntimeError(f"Postal refused the message: {str(d.get('code', ''))} {str(d.get('message', ''))}"[:160].strip())


def send_email(msg, s, secrets=None, host=None):
    if s.get("alert_email_method", "postal") == "postal":
        return send_postal(msg, s, secrets, host)
    sec = secrets or load_secrets()
    to = [a.strip() for a in s["alert_mail_to"].split(",") if a.strip()]
    if not (s["alert_smtp_host"] and s["alert_mail_from"] and to):
        raise RuntimeError("email is not fully configured (server, from, to)")
    m = EmailMessage()
    m["Subject"] = f"[TimeCanvas] {msg['event'].upper()}: {msg['title']}"; m["From"] = s["alert_mail_from"]; m["To"] = ", ".join(to)
    m.set_content(f"{msg['title']}\n\n{msg['detail']}\n\nHost: {host or socket.gethostname()}\nWhen: {msg['when']}\nEvent: {msg['event']}\n")
    port, sec_mode = int(s["alert_smtp_port"]), s["alert_smtp_security"]
    ctx = ssl.create_default_context()
    with (smtplib.SMTP_SSL(s["alert_smtp_host"], port, timeout=20, context=ctx) if sec_mode == "ssl" else smtplib.SMTP(s["alert_smtp_host"], port, timeout=20)) as srv:
        if sec_mode == "starttls":
            srv.starttls(context=ctx)
        if s["alert_smtp_user"] and sec.get("smtp_password"):
            srv.login(s["alert_smtp_user"], sec["smtp_password"])
        srv.send_message(m)


def channels(s, secrets=None):
    sec = secrets or load_secrets(); out = []
    if s["alert_teams_on"] == "1" and sec.get("teams_webhook"):
        out.append("teams")
    if s["alert_email_on"] == "1" and s["alert_mail_to"]:
        if (s["alert_email_method"] == "postal" and s["alert_postal_url"] and sec.get("postal_api_key")) or (s["alert_email_method"] != "postal" and s["alert_smtp_host"]):
            out.append("email")
    return out


def deliver(c, key, event, msg, s, senders=None):
    """Send to every configured channel. Returns True if at least one succeeded (or nothing is configured, so there is nothing to retry)."""
    senders = senders or {"teams": lambda m: send_teams(m), "email": lambda m: send_email(m, s)}
    chans = channels(s)
    if not chans:
        c.execute("INSERT INTO alert_log(ts_utc,key,event,channel,ok,error) VALUES(?,?,?,?,?,?)", (db.utcnow(), key, event, "none", 0, "no channel configured"))
        return True
    any_ok = False
    for ch in chans:
        try:
            senders[ch](msg); ok, err = 1, None; any_ok = True
        except Exception as ex:
            ok, err = 0, f"{type(ex).__name__}: {str(ex)[:150]}"   # never includes the URL or password
            log.error("alert %s via %s failed: %s", key, ch, err)
        c.execute("INSERT INTO alert_log(ts_utc,key,event,channel,ok,error) VALUES(?,?,?,?,?,?)", (db.utcnow(), key, event, ch, ok, err))
    return any_ok


def send_test(c, tz="America/Denver", senders=None, only=None):
    """Send a test through the saved settings. only='teams'|'email'|'heartbeat' tests that one channel on its own (even if its switch is off,
    so you can test before enabling it); otherwise every channel that is switched on and configured. Returns [(channel, ok, message)]."""
    s = get_settings(c); sec = load_secrets()
    msg = {"severity": "info", "title": "TimeCanvas test alert", "detail": "If you can read this, alert delivery works.", "event": "test",
           "when": datetime.now(ZoneInfo(tz)).strftime("%a %H:%M")}
    senders = senders or {"teams": lambda m: send_teams(m), "email": lambda m: send_email(m, s)}
    targets = [only] if only else channels(s, sec)
    if not targets:
        return [("none", False, "switch a channel on and fill in its details first (or use that channel's own test button)")]
    res = []
    for ch in targets:
        try:
            if ch == "heartbeat":
                url = sec.get("heartbeat_url")
                if not url: raise RuntimeError("no heartbeat URL saved")
                if not valid_heartbeat(url): raise RuntimeError("the saved heartbeat URL is not acceptable")
                res.append((ch, True, f"pinged (HTTP {ping_heartbeat(url)})"))
            else:
                if ch == "teams" and not sec.get("teams_webhook"): raise RuntimeError("no Teams webhook URL saved")
                senders[ch](msg); res.append((ch, True, "delivered"))
        except Exception as ex:
            res.append((ch, False, f"{type(ex).__name__}: {str(ex)[:160]}"))
        c.execute("INSERT INTO alert_log(ts_utc,key,event,channel,ok,error) VALUES(?,?,?,?,?,?)", (db.utcnow(), "test", "test", ch, int(res[-1][1]), None if res[-1][1] else res[-1][2]))
    c.commit()
    return res


def beat():
    """Optional dead-man's switch: an external monitor (Uptime Kuma push, healthchecks.io) alerts you when these pings STOP."""
    hb = load_secrets().get("heartbeat_url")
    if hb and valid_heartbeat(hb):
        try:
            ping_heartbeat(hb)
        except Exception as ex:
            log.warning("heartbeat ping failed: %s", str(ex)[:120])


# ---------- state machine ----------
def run(cfg=None, now=None, senders=None, services=service_states, certdays=cert_days):
    cfg = cfg or cfgmod.load()
    c = db.connect(cfg["storage"]["db"]); now = now or datetime.now(timezone.utc)
    s = get_settings(c)
    beat()   # liveness ping first, and regardless of the master switch: switching alerts off must not make the monitor think the VM died
    if s["alerts_enabled"] != "1":
        return 0
    tz = cfgmod.effective(cfg, c)["timezone"]; z = ZoneInfo(tz)
    active = evaluate(c, cfg, s, now, services, certdays)
    for key in set(active) | {r[0] for r in c.execute("SELECT key FROM alert_state")}:
        row = c.execute("SELECT * FROM alert_state WHERE key=?", (key,)).fetchone()
        if key in active:
            sev, title, detail = active[key]
            streak = (row["streak"] if row else 0) + 1
            if not row:
                c.execute("INSERT INTO alert_state(key,severity,status,streak,detail) VALUES(?,?,'ok',1,?)", (key, sev, detail)); row = c.execute("SELECT * FROM alert_state WHERE key=?", (key,)).fetchone()
            else:
                c.execute("UPDATE alert_state SET streak=?, detail=?, severity=? WHERE key=?", (streak, detail, sev, key))
            if streak < 2:
                continue   # must be seen on two consecutive runs: ignores a restart or a single bad sample
            msg = {"severity": sev, "title": title, "detail": detail, "when": now.astimezone(z).strftime("%a %H:%M"), "event": "alert"}
            if row["status"] != "open":
                if deliver(c, key, "opened", msg, s, senders):
                    c.execute("UPDATE alert_state SET status='open', opened_utc=?, last_notified_utc=?, notifies=1, resolved_utc=NULL WHERE key=?", (now.strftime(TS), now.strftime(TS), key))
                else:
                    c.execute("UPDATE alert_state SET status='open', opened_utc=?, last_notified_utc=NULL WHERE key=?", (now.strftime(TS), key))   # delivery failed: retry next run
            else:
                last = _ts(row["last_notified_utc"]) if row["last_notified_utc"] else None
                escalated = row["severity"] != sev and sev == "critical"
                due = last is None or escalated or now - last >= timedelta(hours=int(s["alert_remind_hours"]))
                if due:
                    msg["event"] = "reminder" if last and not escalated else "alert"
                    msg["detail"] = f"Still open for {ago(now - _ts(row['opened_utc']))}. " + detail if row["opened_utc"] else detail
                    if deliver(c, key, "reminder" if last else "opened", msg, s, senders):
                        c.execute("UPDATE alert_state SET last_notified_utc=?, notifies=notifies+1 WHERE key=?", (now.strftime(TS), key))
        elif row and (row["status"] == "open" or row["streak"]):
            if row["status"] == "open":
                label = RULES.get(key, (key,))[0]
                msg = {"severity": "ok", "title": f"Recovered: {label}", "detail": f"Back to normal after {ago(now - _ts(row['opened_utc']))}." if row["opened_utc"] else "Back to normal.",
                       "when": now.astimezone(z).strftime("%a %H:%M"), "event": "recovered"}
                deliver(c, key, "recovered", msg, s, senders)
                c.execute("UPDATE alert_state SET status='ok', streak=0, resolved_utc=? WHERE key=?", (now.strftime(TS), key))
            else:
                c.execute("UPDATE alert_state SET streak=0 WHERE key=?", (key,))
    c.commit()
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run())
