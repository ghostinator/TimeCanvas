import json, os, shutil, sqlite3, stat, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["TIMECANVAS_MIGRATIONS"] = os.path.join(os.path.dirname(__file__), "..", "migrations")   # db binds this at import time
from timecanvas import alerts, db
from test_core import MIG

T0 = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)   # 11:00 in Denver
F = "%Y-%m-%dT%H:%M:%S.%fZ"
OKSVC = lambda: {u: "active" for u in alerts.SERVICES}


class A(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp)
        self.p = [mock.patch.object(alerts, "SECRETS", self.tmp + "/alerts.json")]; [p.start() for p in self.p]; self.addCleanup(lambda: [p.stop() for p in self.p])
        self.c = sqlite3.connect(":memory:"); self.c.row_factory = sqlite3.Row; db.migrate(self.c, MIG)
        self.cfg = {"storage": {"root": self.tmp, "db": ":memory:", "frame_retention_days": 30, "video_retention_days": 365, "disk_warning_percent": 80, "disk_critical_percent": 90},
                    "timezone": "America/Denver", "capture": {"interval_seconds": 30}}
        alerts.save_secrets({"teams_webhook": "https://prod-1.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=SECRETSIG"})
        for k, v in (("alert_teams_on", "1"), ("alert_remind_hours", "6")): alerts.put(self.c, k, v)
        self.c.commit(); self.sent = []; self.broken = False
        def teams(m):
            if self.broken: raise RuntimeError("down")
            self.sent.append((m["event"], m["title"], m["severity"]))
        self.senders = {"teams": teams, "email": lambda m: None}
        self.now = T0

    def status(self, **kw):
        st = {"ts_utc": self.now.strftime(F), "camera_online": True, "disk_pct": 5.0, **kw}
        alerts.put(self.c, "status", json.dumps(st)); self.c.commit()

    def cap(self, status, minutes_ago=0, detail=None):
        self.c.execute("INSERT INTO capture_events(ts_utc,status,detail) VALUES(?,?,?)", ((self.now - timedelta(minutes=minutes_ago)).strftime(F), status, detail)); self.c.commit()

    def tick(self, minutes=1, **status):
        self.now += timedelta(minutes=minutes); self.status(**status)
        with mock.patch.object(alerts.db, "connect", lambda *_: self.c):
            alerts.run(self.cfg, now=self.now, senders=self.senders, services=OKSVC, certdays=lambda: 80)

    def events(self): return [(e, t) for e, t, _ in self.sent]

    def test_healthy_system_is_silent(self):
        for _ in range(5): self.cap("ok"); self.tick()
        self.assertEqual(self.sent, [])

    def test_camera_offline_opens_after_threshold_and_confirmation_then_reminds_then_recovers(self):
        self.cap("ok", 30)
        self.c.execute("INSERT INTO health_events(ts_utc,level,source,message) VALUES(?,?,?,?)", ((self.now + timedelta(minutes=1)).strftime(F), "error", "camera", "camera offline")); self.c.commit()
        for _ in range(3): self.tick(camera_online=False)           # 1-3 min offline: below the 3 min threshold
        self.assertEqual(self.sent, [])
        self.tick(camera_online=False)                               # threshold reached (first evaluation)
        self.assertEqual(self.sent, [])                              # needs a second consecutive sighting
        self.tick(camera_online=False)
        self.assertEqual(self.events(), [("alert", "Camera offline")])
        for _ in range(60): self.tick(camera_online=False)           # an hour: no repeat spam
        self.assertEqual(len(self.sent), 1)
        for _ in range(300): self.tick(camera_online=False)          # past 6 h: one reminder
        self.assertEqual([e for e, _ in self.events()], ["alert", "reminder"])
        self.cap("ok"); self.tick(camera_online=True)             # camera is back and a photo arrives
        self.assertEqual(self.events()[-1], ("recovered", "Recovered: Camera offline"))
        self.assertEqual(len(self.sent), 3)
        self.cap("ok"); self.tick(); self.assertEqual(len(self.sent), 3)   # and silence afterwards

    def test_no_new_photos_alert_for_non_offline_cause_and_suppressed_when_offline_alert_covers_it(self):
        for _ in range(14): self.cap("failed", 0, "not a complete JPEG"); self.tick()   # ~14 min of failures, camera claims online
        self.assertEqual(self.events(), [("alert", "No new photos")])
        self.assertIn("not a complete JPEG", self.c.execute("SELECT detail FROM alert_state WHERE key='capture_stale'").fetchone()[0])
        self.sent.clear()
        # offline cause: only the camera alert, never both
        self.c.execute("DELETE FROM alert_state"); self.c.commit()
        self.c.execute("INSERT INTO health_events(ts_utc,level,source,message) VALUES(?,?,?,?)", ((self.now - timedelta(minutes=20)).strftime(F), "error", "camera", "camera offline")); self.c.commit()
        for _ in range(4): self.tick(camera_online=False)
        self.assertEqual(sorted(t for _, t in self.events()), ["Camera offline"])

    def test_schedule_window_start_is_not_a_false_alarm_and_disabled_capture_is_silent(self):
        # a session that only captures 08-17 local; it is 07:59 -> 08:05 local (13:59-14:05 UTC), last ok photo was yesterday
        self.now = datetime(2026, 11, 22, 13, 59, tzinfo=timezone.utc)
        self.c.execute("INSERT INTO sessions(name,start_utc,interval_seconds,schedule_json,created_utc) VALUES('day','2026-11-01T00:00:00.000000Z',NULL,?,'x')", (json.dumps({"hours": [8, 17]}),))
        self.c.commit(); self.cap("ok", 14 * 60)
        for _ in range(8): self.tick()
        self.assertEqual(self.sent, [])
        alerts.put(self.c, "capture_enabled", "0"); self.c.commit()
        self.now = T0
        for _ in range(15): self.tick()
        self.assertEqual(self.sent, [])

    def test_disk_warning_then_critical_escalates_once(self):
        self.cap("ok")
        for _ in range(3): self.cap("ok"); self.tick(disk_pct=85.0)
        self.assertEqual(self.sent, [("alert", "Disk filling up", "warning")])
        for _ in range(3): self.cap("ok"); self.tick(disk_pct=93.0)
        self.assertEqual(self.sent[-1], ("alert", "Disk full", "critical")); self.assertEqual(len(self.sent), 2)

    def test_rule_can_be_switched_off_and_master_switch(self):
        alerts.put(self.c, "alert_on_disk", "0"); self.c.commit()
        for _ in range(4): self.cap("ok"); self.tick(disk_pct=95.0)
        self.assertEqual(self.sent, [])
        alerts.put(self.c, "alerts_enabled", "0"); alerts.put(self.c, "alert_on_disk", "1"); self.c.commit()
        for _ in range(4): self.cap("ok"); self.tick(disk_pct=95.0)
        self.assertEqual(self.sent, [])

    def test_service_down_needs_two_runs_and_certificate_expiry(self):
        bad = lambda: {**OKSVC(), "ustreamer.service": "failed"}
        for _ in range(3):
            self.cap("ok"); self.now += timedelta(minutes=1); self.status()
            with mock.patch.object(alerts.db, "connect", lambda *_: self.c): alerts.run(self.cfg, now=self.now, senders=self.senders, services=bad, certdays=lambda: 2)
        self.assertEqual(sorted(t for _, t in self.events()), ["HTTPS certificate expiring", "Service problem"])
        self.assertEqual(sorted(s for _, _, s in self.sent), ["critical", "critical"])

    def test_failed_delivery_is_retried_and_logged_without_leaking_secrets(self):
        self.broken = True
        for _ in range(3): self.cap("ok"); self.tick(disk_pct=95.0)
        self.assertEqual(self.sent, [])
        self.broken = False; self.tick(disk_pct=95.0)
        self.assertEqual(len(self.sent), 1)                                          # retried on the next run
        log = self.c.execute("SELECT ok,error FROM alert_log ORDER BY id").fetchall()
        self.assertTrue(any(r["ok"] == 0 for r in log) and any(r["ok"] == 1 for r in log))
        self.assertNotIn("SECRETSIG", " ".join(str(r["error"]) for r in log))

    def test_no_channel_configured_does_not_loop(self):
        alerts.put(self.c, "alert_teams_on", "0"); self.c.commit()
        for _ in range(6): self.cap("ok"); self.tick(disk_pct=95.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM alert_log WHERE channel='none'").fetchone()[0], 1)   # logged once, not every minute

    def test_validation_and_secret_file(self):
        good = "https://prod-12.northeurope.logic.azure.com:443/workflows/x/triggers/manual/paths/invoke?sig=y"
        self.assertTrue(alerts.valid_webhook(good)); self.assertTrue(alerts.valid_webhook("https://x.environment.api.powerplatform.com/powerautomate/automations/direct/workflows/1/triggers/manual/paths/invoke"))
        for bad in ("http://prod.logic.azure.com/x", "https://evil.example.com/x", "https://u:p@prod.logic.azure.com/x", "https://prod.logic.azure.com:8443/x", "https://logic.azure.com.evil.com/x", "file:///etc/passwd", "https://127.0.0.1/x", ""):
            self.assertFalse(alerts.valid_webhook(bad), bad)
        for ok in ("https://hc-ping.com/abc-123", "http://100.64.0.5:3001/api/push/Tok3n?status=up&msg=OK&ping=", "http://192.168.1.50:3001/api/push/x", "http://kuma.example.ts.net:3001/api/push/x", "http://kuma:3001/x"):
            self.assertTrue(alerts.valid_heartbeat(ok), ok)
        for bad in ("http://127.0.0.1/x", "http://localhost:3001/x", "http://169.254.169.254/latest/meta-data", "http://0.0.0.0/x", "http://[::1]/x", "http://u:p@100.64.0.5/x", "ftp://100.64.0.5/x", "http://224.0.0.1/x", "", "http://foo.localhost/x", "http://a b/x", "http://" + "a" * 600):
            self.assertFalse(alerts.valid_heartbeat(bad), bad)
        self.assertTrue(alerts.valid_email("a.b@example.com")); self.assertFalse(alerts.valid_email("a@b")); self.assertFalse(alerts.valid_email("a@b.com, c@d.com"))
        self.assertEqual(stat.S_IMODE(os.stat(alerts.SECRETS).st_mode), 0o600)
        alerts.save_secrets({"teams_webhook": ""}); self.assertNotIn("teams_webhook", alerts.load_secrets())

    def test_card_and_email_payloads(self):
        m = {"severity": "critical", "title": "Camera offline", "detail": "d", "event": "alert", "when": "Sun 11:00"}
        c = alerts.card(m, "host1"); self.assertEqual(c["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")
        self.assertEqual(c["attachments"][0]["content"]["body"][0]["color"], "Attention")
        sent = {}
        class FakeSMTP:
            def __init__(s, *a, **k): sent["args"] = a
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def starttls(s, **k): sent["tls"] = True
            def login(s, u, p): sent["login"] = (u, p)
            def send_message(s, msg): sent["subject"] = msg["Subject"]; sent["to"] = msg["To"]
        st = {**alerts.DEFAULTS, "alert_email_method": "smtp", "alert_smtp_host": "smtp.example.com", "alert_mail_from": "tc@example.com", "alert_mail_to": "me@example.com, you@example.com", "alert_smtp_user": "u"}
        with mock.patch.object(alerts.smtplib, "SMTP", FakeSMTP):
            alerts.send_email(m, st, secrets={"smtp_password": "pw"}, host="host1")
        self.assertEqual(sent["subject"], "[TimeCanvas] ALERT: Camera offline"); self.assertTrue(sent["tls"]); self.assertEqual(sent["login"], ("u", "pw")); self.assertEqual(sent["to"], "me@example.com, you@example.com")
        with self.assertRaises(RuntimeError): alerts.send_email(m, alerts.DEFAULTS)

    def test_postal_api_request_shape_errors_and_channel_selection(self):
        st = {**alerts.DEFAULTS, "alert_email_method": "postal", "alert_postal_url": "https://postal.example.com/", "alert_mail_from": "tc@example.com", "alert_mail_to": "me@example.com, you@example.com"}
        m = {"severity": "critical", "title": "Camera offline", "detail": "d", "event": "alert", "when": "Sun 11:00"}
        seen = {}
        class Resp:
            def __init__(s, body): s.body = body
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s): return s.body
        def fake_open(reply):
            class Op:
                def open(s, req, timeout=None):
                    seen.update(url=req.full_url, key=req.get_header("X-server-api-key"), ua=req.get_header("User-agent"), body=json.loads(req.data), method=req.get_method(), timeout=timeout)
                    if isinstance(reply, Exception): raise reply
                    return Resp(reply)
            return lambda *h: Op()
        with mock.patch.object(alerts.urllib.request, "build_opener", fake_open(b'{"status":"success","data":{"message_id":"x"}}')):
            alerts.send_email(m, st, secrets={"postal_api_key": "KEY12345678"}, host="h1")
        self.assertEqual((seen["url"], seen["key"], seen["method"]), ("https://postal.example.com/api/v1/send/message", "KEY12345678", "POST"))
        self.assertEqual(seen["ua"], alerts.UA); self.assertNotIn("Python-urllib", seen["ua"])                            # Cloudflare 1010 blocks the default UA
        self.assertEqual(seen["body"]["to"], ["me@example.com", "you@example.com"]); self.assertEqual(seen["body"]["from"], "tc@example.com")
        self.assertEqual(seen["body"]["subject"], "[TimeCanvas] ALERT: Camera offline"); self.assertIn("Host: h1", seen["body"]["plain_body"])
        with mock.patch.object(alerts.urllib.request, "build_opener", fake_open(b'{"status":"error","data":{"code":"FromAddressNotVerified","message":"nope"}}')):
            with self.assertRaises(RuntimeError) as cm: alerts.send_email(m, st, secrets={"postal_api_key": "KEY12345678"})
        self.assertIn("FromAddressNotVerified", str(cm.exception)); self.assertNotIn("KEY12345678", str(cm.exception))
        import io
        err = alerts.urllib.error.HTTPError("https://x", 403, "no", {}, io.BytesIO(b"error code: 1010 KEY12345678"))
        with mock.patch.object(alerts.urllib.request, "build_opener", fake_open(err)):
            with self.assertRaises(RuntimeError) as cm: alerts.send_email(m, st, secrets={"postal_api_key": "KEY12345678"})
        self.assertIn("HTTP 403", str(cm.exception)); self.assertIn("1010", str(cm.exception)); self.assertNotIn("KEY12345678", str(cm.exception))   # real reason shown, key never
        for bad in ({**st, "alert_postal_url": "http://postal.example.com"}, {**st, "alert_postal_url": "https://127.0.0.1"}, {**st, "alert_mail_to": ""}):
            with self.assertRaises(RuntimeError): alerts.send_email(m, bad, secrets={"postal_api_key": "KEY12345678"})
        with self.assertRaises(RuntimeError): alerts.send_email(m, st, secrets={})                                      # no key
        self.assertEqual(alerts.channels({**st, "alert_email_on": "1"}, {"postal_api_key": "k"}), ["email"])
        self.assertEqual(alerts.channels({**st, "alert_email_on": "1"}, {}), [])                                         # key missing -> channel not active
        self.assertEqual(alerts.channels({**st, "alert_email_on": "1", "alert_email_method": "smtp"}, {}), [])           # smtp without host

    def test_each_channel_can_be_tested_on_its_own(self):
        alerts.put(self.c, "alert_teams_on", "0"); self.c.commit()                                                     # Teams switched OFF but saved
        calls = []
        senders = {"teams": lambda m: calls.append("teams"), "email": lambda m: (_ for _ in ()).throw(RuntimeError("Postal refused: bad key"))}
        r = alerts.send_test(self.c, "America/Denver", senders=senders, only="teams")
        self.assertEqual(r, [("teams", True, "delivered")]); self.assertEqual(calls, ["teams"])                        # worked although the switch is off
        r = alerts.send_test(self.c, "America/Denver", senders=senders, only="email")
        self.assertEqual((r[0][0], r[0][1]), ("email", False)); self.assertIn("bad key", r[0][2]); self.assertEqual(calls, ["teams"])   # a failing email test does not touch Teams
        alerts.save_secrets({"teams_webhook": ""})
        self.assertIn("no Teams webhook", alerts.send_test(self.c, "America/Denver", senders=senders, only="teams")[0][2])
        self.assertEqual(alerts.send_test(self.c, "America/Denver", senders=senders)[0][0], "none")                      # nothing switched on
        alerts.save_secrets({"heartbeat_url": "http://100.64.0.5:3001/api/push/tok"})
        with mock.patch.object(alerts, "ping_heartbeat", lambda u: 200):
            self.assertEqual(alerts.send_test(self.c, "America/Denver", only="heartbeat"), [("heartbeat", True, "pinged (HTTP 200)")])
        alerts.save_secrets({"heartbeat_url": ""})
        self.assertIn("no heartbeat URL", alerts.send_test(self.c, "America/Denver", only="heartbeat")[0][2])
        logs = self.c.execute("SELECT channel,ok FROM alert_log WHERE key='test'").fetchall(); self.assertTrue(any(r["channel"] == "email" and r["ok"] == 0 for r in logs))

    def test_heartbeat_pings_every_run_even_with_alerts_switched_off(self):
        alerts.save_secrets({"heartbeat_url": "http://100.64.0.5:3001/api/push/tok"})
        pings = []
        with mock.patch.object(alerts, "ping_heartbeat", lambda u: pings.append(u) or 200):
            self.tick()
            alerts.put(self.c, "alerts_enabled", "0"); self.c.commit()
            self.tick()
            alerts.save_secrets({"heartbeat_url": ""}); self.tick()
        self.assertEqual(len(pings), 2)                                                                                 # on and off: pinged; no URL: not pinged
        with mock.patch.object(alerts, "ping_heartbeat", lambda u: (_ for _ in ()).throw(RuntimeError("monitor down"))):
            alerts.save_secrets({"heartbeat_url": "http://100.64.0.5:3001/api/push/tok"}); self.tick()                 # a failing monitor never breaks alerting

    def test_redirects_are_not_followed(self):
        h = alerts._NoRedirect()
        self.assertIsNone(h.redirect_request(None, None, 302, "Found", {}, "http://evil.example"))


if __name__ == "__main__":
    unittest.main()
