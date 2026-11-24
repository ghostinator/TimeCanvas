"""One capture tick. Run by timecanvas-capture.service every few seconds; does work only when a slot is due."""
import fcntl, hashlib, logging, os, shutil, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config as cfgmod, db, jpeg, paths

OK, BUSY_OR_SKIP, CAMERA, DISK_CRITICAL, IOERR = 0, 0, 2, 3, 4
log = logging.getLogger("timecanvas.capture")
LOCK = "/run/timecanvas/capture.lock"  # shared lock dir; cleanup/render use their own files


def slot_of(epoch, interval):
    return int(epoch // interval)


def clamp_interval(v):
    return max(10, min(3600, int(v)))


def filename_for(dt_utc, tz):
    local = dt_utc.astimezone(ZoneInfo(tz))
    stem = local.strftime("%Y-%m-%dT%H-%M-%S%z")  # e.g. 2026-11-19T09-01-30-0700
    return f"images/{local:%Y/%m/%d}/{stem}.jpg"


def active_session(c, now, tz):
    """Return (interval_override or None, allowed_now). Sessions only tighten/override interval and may gate by days/hours."""
    import json
    iso = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    rows = c.execute("SELECT interval_seconds,schedule_json FROM sessions WHERE start_utc<=? AND (end_utc IS NULL OR end_utc>?) ORDER BY id DESC", (iso, iso)).fetchall()
    if not rows:
        return None, True
    r = rows[0]
    sch = json.loads(r["schedule_json"]) if r["schedule_json"] else {}
    local = now.astimezone(ZoneInfo(tz))
    if sch.get("days") and local.weekday() not in sch["days"]:
        return r["interval_seconds"], False
    if sch.get("hours") and not (sch["hours"][0] <= local.hour < sch["hours"][1]):
        return r["interval_seconds"], False
    return r["interval_seconds"], True


def disk_level(pct, warn, crit):
    return "critical" if pct >= crit else "warning" if pct >= warn else "ok"


def validate_snapshot(headers, data, want_w, want_h, max_age):
    # want_w/want_h are fallbacks; the streamer reports its live size in X-UStreamer-Width/Height, which wins.
    """ustreamer serves a placeholder JPEG (HTTP 200) when the camera is gone: trust headers, not just the JPEG."""
    if headers.get("X-UStreamer-Online", "").lower() != "true":
        raise ValueError("camera offline (placeholder frame)")
    grab = float(headers.get("X-UStreamer-Grab-Timestamp", "0"))
    expose = float(headers.get("X-UStreamer-Expose-Begin-Timestamp", "0"))
    if grab <= 0 or expose - grab > max_age:
        raise ValueError("stale frame")
    w, h = jpeg.inspect(data)
    want_w = int(headers.get("X-UStreamer-Width") or want_w)
    want_h = int(headers.get("X-UStreamer-Height") or want_h)
    if (w, h) != (want_w, want_h):
        raise ValueError(f"unexpected size {w}x{h}")
    return w, h


def fetch(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        if r.status != 200:
            raise ValueError(f"HTTP {r.status}")
        return dict(r.headers.items()), r.read()


def record(c, status, detail=None, media_id=None, ms=None):
    c.execute("INSERT INTO capture_events(ts_utc,status,detail,media_id,duration_ms) VALUES(?,?,?,?,?)",
              (db.utcnow(), status, detail, media_id, ms))
    c.commit()


def check_disk(c, root, warn, crit):
    u = shutil.disk_usage(root)
    pct = 100.0 * (u.total - u.free) / u.total
    level = disk_level(pct, warn, crit)
    if db.get_setting(c, "disk_level", "ok") != level:
        db.health(c, {"ok": "info", "warning": "warning", "critical": "critical"}[level], "disk", f"disk {level}: {pct:.1f}% used")
        c.execute("INSERT INTO settings(key,value,updated_utc) VALUES('disk_level',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc",
                  (level, db.utcnow()))
        c.commit()
    return level, pct


def run(cfg=None, now=None, force=False):
    cfg = cfg or cfgmod.load()
    st, cam, cap = cfg["storage"], cfg["camera"], cfg["capture"]
    root = st["root"]
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lockf = open(LOCK, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("another capture/cleanup holds the lock; skipping")
        return BUSY_OR_SKIP
    if not os.path.ismount(root):
        log.error("%s is not a mount point; refusing to write", root)
        return IOERR
    c = db.connect(st["db"])
    t0 = time.time()
    now = now or datetime.now(timezone.utc)
    cfg = cfgmod.effective(cfg, c); st, cap = cfg["storage"], cfg["capture"]
    if db.get_setting(c, "capture_enabled", "1") != "1" and not force:
        return OK
    tzname = cfg.get("timezone", "America/Denver")
    s_iv, s_ok = active_session(c, now, tzname)
    if not s_ok and not force:
        return OK
    interval = clamp_interval(s_iv or cap["interval_seconds"])
    last = c.execute("SELECT ts_utc FROM capture_events WHERE status!='skipped' ORDER BY id DESC LIMIT 1").fetchone()
    if last and not force:
        last_epoch = datetime.strptime(last[0], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
        if slot_of(last_epoch, interval) == slot_of(now.timestamp(), interval):
            return OK  # this slot already handled (success or failure): one attempt per slot, one catch-up after downtime
    level, pct = check_disk(c, root, st["disk_warning_percent"], st["disk_critical_percent"])
    if level == "critical":
        record(c, "blocked_disk", f"disk {pct:.1f}% >= critical")
        return DISK_CRITICAL
    err = None
    for attempt in range(3):  # truncated frames happen occasionally on the passthrough link; retry briefly before giving up
        try:
            headers, data = fetch(cam["streamer_url"] + "/snapshot", cap["http_timeout_seconds"])
            w, h = validate_snapshot(headers, data, cam["width"], cam["height"], cap["max_frame_age_seconds"])
            err = None
            break
        except Exception as e:  # network, timeout, offline, stale, malformed
            err = e
            if "offline" in str(e):
                break
            time.sleep(0.7)
    if err is not None:
        record(c, "failed", str(err)[:200], ms=int((time.time() - t0) * 1000))
        log.warning("capture failed: %s", err)
        return CAMERA
    tz = cfg.get("timezone", "America/Denver")
    final = paths.safe_path(os.path.join(root, filename_for(now, tz)), root)
    tmp = os.path.join(root, "tmp", f".cap-{os.getpid()}-{int(t0*1000)}.jpg")
    try:
        os.makedirs(os.path.dirname(final), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, final)  # atomic and refuses to overwrite an existing file
        os.unlink(tmp)
        dfd = os.open(os.path.dirname(final), os.O_RDONLY)
        os.fsync(dfd)
        os.close(dfd)
    except FileExistsError:
        os.path.exists(tmp) and os.unlink(tmp)
        record(c, "failed", "target exists; not overwriting")
        return IOERR
    except OSError as e:
        os.path.exists(tmp) and os.unlink(tmp)
        record(c, "failed", f"io error: {e}"[:200])
        return IOERR
    cur = c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,sha256,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                    (final, "image", now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), tz, w, h, len(data), hashlib.sha256(data).hexdigest(), db.utcnow()))
    record(c, "ok", f"{w}x{h} {len(data)}B", cur.lastrowid, int((time.time() - t0) * 1000))
    log.info("captured %s", final)
    return OK


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run(force="--force" in sys.argv))


if __name__ == "__main__":
    main()
