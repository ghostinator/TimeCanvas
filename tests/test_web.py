from datetime import datetime, timedelta, timezone
import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
try:
    from fastapi.testclient import TestClient
except Exception:  # fastapi/httpx not installed locally
    TestClient = None

AUTH = {"X-Remote-User": "tester"}


@unittest.skipUnless(TestClient, "fastapi+httpx not installed")
class W(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, "srv"); [os.makedirs(root + d) for d in ("/thumbnails", "/images", "/tmp", "/videos/custom")]; cls.root = root
        cfg = os.path.join(cls.tmp, "c.toml")
        open(cfg, "w").write(open(os.path.join(os.path.dirname(__file__), "..", "config", "config.example.toml")).read()
                             .replace("/srv/timecanvas", root).replace("/var/lib/timecanvas/timecanvas.db", cls.tmp + "/t.db"))
        os.environ["TIMECANVAS_CONFIG"] = cfg
        os.environ["TIMECANVAS_MIGRATIONS"] = os.path.join(os.path.dirname(__file__), "..", "migrations")
        from timecanvas import config; config.PATH = cfg
        from timecanvas.web import app as webapp
        webapp.helper = lambda *a, **k: (False, "no helper in tests")
        webapp.alerts.SECRETS = cls.tmp + "/alerts.json"
        webapp.svc = lambda u: "active"
        cls.c = TestClient(webapp.app, base_url="https://testserver")

    def test_requires_auth_header(self):
        self.assertEqual(self.c.get("/").status_code, 401)
        self.assertEqual(self.c.get("/media/1/file").status_code, 401)
        self.assertEqual(self.c.post("/settings", data={}).status_code, 401)

    def test_pages_render_with_auth(self):
        for p in ("/", "/library", "/renders", "/sessions", "/camera", "/settings", "/maintenance", "/partials/status"):
            r = self.c.get(p, headers=AUTH); self.assertEqual(r.status_code, 200, p)
        self.assertIn("TimeCanvas", self.c.get("/", headers=AUTH).text)

    def test_csrf_enforced(self):
        self.c.get("/settings", headers=AUTH)
        tok = self.c.cookies.get("tc_csrf")
        self.assertTrue(tok)
        self.assertEqual(self.c.post("/settings", headers=AUTH, data={"capture_interval_seconds": "30"}).status_code, 403)       # no token
        self.assertEqual(self.c.post("/settings", headers={**AUTH, "X-CSRF-Token": "wrong"}, data={}).status_code, 403)
        self.assertEqual(self.c.post("/settings", headers={**AUTH, "X-CSRF-Token": tok, "Origin": "https://evil.example"}, data={}).status_code, 403)
        r = self.c.post("/settings", headers={**AUTH, "X-CSRF-Token": tok}, data={}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)  # passes CSRF; rejected by validation, not by csrf

    def test_settings_validation(self):
        self.c.get("/settings", headers=AUTH); tok = self.c.cookies.get("tc_csrf")
        good = {"capture_interval_seconds": "30", "frame_retention_days": "30", "video_retention_days": "365", "disk_warning_percent": "80",
                "disk_critical_percent": "90", "render_fps": "30", "render_crf": "23", "render_preset": "medium", "timezone": "America/Denver", "capture_enabled": "on"}
        h = {**AUTH, "X-CSRF-Token": tok}
        for k, v in (("capture_interval_seconds", "5"), ("disk_warning_percent", "95"), ("render_preset", "x;rm"), ("timezone", "Mars/Base"), ("render_crf", "abc")):
            r = self.c.post("/settings", headers=h, data={**good, k: v}, follow_redirects=False)
            self.assertIn("invalid", r.headers["location"], k)
        r = self.c.post("/settings", headers=h, data=good, follow_redirects=False)
        self.assertIn("saved", r.headers["location"])

    def test_media_path_never_from_browser(self):
        self.assertEqual(self.c.get("/media/abc/file", headers=AUTH).status_code, 422)
        self.assertEqual(self.c.get("/media/999/file", headers=AUTH).status_code, 404)
        self.assertEqual(self.c.get("/static/../../etc/passwd", headers=AUTH).status_code, 404)

    def test_camera_page_renders_modes_and_controls(self):
        from test_camera import FORMATS, CTRLS
        from timecanvas.web import app as webapp
        old = webapp.helper
        webapp.helper = lambda *a, **k: (True, FORMATS + CTRLS + "#MODE 1920x1080 30\n")
        try:
            t = self.c.get("/camera", headers=AUTH).text
        finally:
            webapp.helper = old
        self.assertIn("1920×1080 @ 30 fps", t); self.assertIn("1280×720 @ 25 fps", t)
        self.assertNotIn("640×480", t)                       # not an MJPG mode
        self.assertIn('type="range"', t); self.assertIn("Aperture Priority Mode", t)
        self.assertIn("inactive (auto mode on)", t)           # white_balance_temperature while auto WB is on
        self.assertIn('hx-post="/camera/mode"', t); self.assertIn('/live/stream', t)

    def test_camera_mode_and_set_need_csrf_and_validate(self):
        self.c.get("/camera", headers=AUTH); tok = self.c.cookies.get("tc_csrf")
        self.assertEqual(self.c.post("/camera/mode", headers=AUTH, data={"mode": "1920x1080x30"}).status_code, 403)
        self.assertEqual(self.c.post("/camera/reset", headers=AUTH).status_code, 403)
        h = {**AUTH, "X-CSRF-Token": tok, "HX-Request": "true"}
        r = self.c.post("/camera/mode", headers=h, data={"mode": "garbage"})
        self.assertEqual(r.status_code, 200); self.assertIn("bad mode", r.text)
        r = self.c.post("/camera/set", headers=h, data={"name": "brightness", "value": "abc"})
        self.assertIn("must be an integer", r.text)

    # ---- file management ----
    def _seed(self, n=4):
        from datetime import datetime, timedelta, timezone
        from timecanvas.web import app as webapp
        from test_core import make_jpeg
        c = webapp.conn(); c.execute("DELETE FROM pinned_media"); c.execute("DELETE FROM capture_events"); c.execute("DELETE FROM media_files"); c.execute("DELETE FROM audit_events"); c.commit()
        for f in os.listdir(self.root + "/images"):
            os.unlink(f"{self.root}/images/{f}")
        t0 = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc); ids = []
        for i in range(n):
            p = f"{self.root}/images/s{i}.jpg"; open(p, "wb").write(make_jpeg())
            c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)",
                      (p, "image", (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "America/Denver", 1280, 720, os.path.getsize(p), "x"))
            ids.append(c.execute("select last_insert_rowid()").fetchone()[0])
        c.commit()
        return c, ids

    def _h(self):
        self.c.get("/storage", headers=AUTH)
        return {**AUTH, "X-CSRF-Token": self.c.cookies.get("tc_csrf")}

    def test_bulk_requires_csrf_selection_and_confirm(self):
        c, ids = self._seed(); h = self._h()
        self.assertEqual(self.c.post("/library/bulk", headers=AUTH, data={"action": "delete"}).status_code, 403)
        r = self.c.post("/library/bulk", headers=h, data={"action": "delete"}, follow_redirects=False)
        self.assertIn("select", r.headers["location"])                                  # nothing selected
        r = self.c.post("/library/bulk", headers=h, data={"action": "delete", "ids": [str(ids[0])]}, follow_redirects=False)
        self.assertIn("confirmation", r.headers["location"]); self.assertEqual(len(os.listdir(self.root + "/images")), 4)
        r = self.c.post("/library/bulk", headers=h, data={"action": "delete", "ids": ["abc", "1; DROP TABLE x"]}, follow_redirects=False)
        self.assertIn("select", r.headers["location"])                                  # non-numeric ids are ignored

    def test_bulk_pin_delete_keeps_pinned_and_zip_downloads(self):
        c, ids = self._seed(); h = self._h()
        self.c.post("/library/bulk", headers=h, data={"action": "pin", "ids": [str(ids[0])]})
        r = self.c.post("/library/bulk", headers=h, data={"action": "delete", "confirm": "yes", "ids": [str(i) for i in ids]}, follow_redirects=False)
        self.assertIn("3", r.headers["location"]); self.assertIn("skipped", r.headers["location"])
        self.assertEqual(os.listdir(self.root + "/images"), ["s0.jpg"])                 # pinned survived
        z = self.c.post("/library/bulk", headers=h, data={"action": "zip", "ids": [str(ids[0])]})
        self.assertEqual(z.headers["content-type"], "application/zip"); self.assertTrue(z.content.startswith(b"PK"))
        self.assertEqual(os.listdir(self.root + "/tmp"), [])                            # temp zip cleaned up after sending

    def test_storage_day_actions_and_range_preview_matches_delete(self):
        c, ids = self._seed(); h = self._h()
        self.assertIn("2026-11-19", self.c.get("/storage?month=2026-11", headers=AUTH).text)
        self.c.post("/storage/day", headers=h, data={"day": "2026-11-19", "action": "pin"})
        self.assertEqual(c.execute("select count(*) from pinned_media").fetchone()[0], 4)
        self.c.post("/storage/day", headers=h, data={"day": "2026-11-19", "action": "unpin"})
        self.assertEqual(self.c.post("/storage/day", headers=h, data={"day": "2026-11-19", "action": "delete"}, follow_redirects=False).headers["location"].count("confirmation"), 1)
        c.execute("INSERT INTO pinned_media VALUES(?,?,NULL)", (ids[1], "t")); c.commit()
        q = {"from": "2026-11-19", "to": "2026-11-19", "type": "frames"}
        pv = self.c.get("/storage/range-preview", headers=AUTH, params=q).text
        self.assertIn("<b>3</b>", pv); self.assertIn("1 pinned", pv)
        r = self.c.post("/storage/range-delete", headers=h, data={**q, "confirm": "yes"}, follow_redirects=False)
        from urllib.parse import unquote
        self.assertIn("3 deleted", unquote(r.headers["location"])); self.assertEqual(os.listdir(self.root + "/images"), ["s1.jpg"])
        self.assertIn("valid", self.c.get("/storage/range-preview", headers=AUTH, params={"from": "x", "to": "y"}).text)
        self.assertEqual(self.c.post("/storage/range-delete", headers=h, data={**q}, follow_redirects=False).headers["location"].count("confirmation"), 1)

    def test_video_list_sorts_and_shows_duration(self):
        c, _ = self._seed(1)
        for name, size, dur, day in (("a.mp4", 100, 5.0, 19), ("b.mp4", 900, 61.0, 18)):
            p = f"{self.root}/videos/custom/{name}"; open(p, "wb").write(b"x" * size)
            c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc,duration) VALUES(?,?,?,?,?,?,?,?,?)",
                      (p, "video", f"2026-11-{day}T00:00:00.000000Z", "America/Denver", 1280, 720, size, "x", dur))
        c.commit()
        t = self.c.get("/library?tab=videos&vsort=size&vdir=desc", headers=AUTH).text
        self.assertLess(t.index("b.mp4"), t.index("a.mp4")); self.assertIn("1:01", t)
        t = self.c.get("/library?tab=videos&vsort=duration&vdir=asc", headers=AUTH).text
        self.assertLess(t.index("a.mp4"), t.index("b.mp4"))
        self.assertEqual(self.c.get("/library?tab=videos&vsort=%3Bdrop&vdir=x", headers=AUTH).status_code, 200)   # unknown sort key falls back

    def test_library_pagination(self):
        self._seed(30)
        t = self.c.get("/library?day=2026-11-19&per_page=24", headers=AUTH).text
        self.assertEqual(t.count('name="ids" value'), 24); self.assertIn("page 1 of 2", t)
        t = self.c.get("/library?day=2026-11-19&per_page=24&page_no=2", headers=AUTH).text
        self.assertEqual(t.count('name="ids" value'), 6)
        t = self.c.get("/library?day=2026-11-19&per_page=999&page_no=99", headers=AUTH).text   # bad size -> 60, page clamped
        self.assertEqual(t.count('name="ids" value'), 30); self.assertIn("1", t)

    def test_library_tabs_filter_play_and_timed_render(self):
        from timecanvas.web import app as webapp
        self._seed(10)
        t = self.c.get("/library?day=2026-11-19&tfrom=01:00&tto=02:00", headers=AUTH).text
        self.assertEqual(t.count('name="ids" value'), 0)                       # nothing captured in that window
        t = self.c.get("/library?day=2026-11-19&fsort=size&fdir=desc&fpinned=1", headers=AUTH).text
        self.assertEqual(t.count('name="ids" value'), 0)                       # nothing pinned
        self.assertIn("data-autosubmit", t); self.assertNotIn("onchange", t)   # CSP: no inline handlers
        self.assertEqual(self.c.get("/library?tab=videos&q=%25_%5C", headers=AUTH).status_code, 200)   # LIKE wildcards are escaped
        j = self.c.get("/play/frames?start=2026-11-19T00:00&end=2026-11-20T00:00", headers=AUTH).json()
        self.assertEqual((j["total"], len(j["frames"])), (10, 10))
        self.assertEqual(len(self.c.get("/play/frames?start=2026-11-19T00:00&end=2026-11-20T00:00&step=5", headers=AUTH).json()["frames"]), 2)
        self.assertEqual(self.c.get("/play/frames?start=2026-11-20T00:00&end=2026-11-19T00:00", headers=AUTH).status_code, 400)
        self.assertEqual(self.c.get("/play/frames?start=junk&end=x", headers=AUTH).status_code, 400)
        self.assertEqual(self.c.get("/play", headers=AUTH).status_code, 200)
        r = self.c.get(f"/media/{j['frames'][0][0]}/file", headers=AUTH)       # preloaded frames must stay in the browser cache
        self.assertIn("max-age", r.headers["cache-control"])
        self.assertNotIn("max-age", self.c.get(f"/media/{j['frames'][0][0]}/file?dl=1", headers=AUTH).headers.get("cache-control", ""))
        h = self._h()
        r = self.c.post("/renders", headers=h, data={"kind": "custom", "start": "2026-11-19T01:30", "end": "2026-11-19T02:45", "format": "webp"}, follow_redirects=False)
        self.assertIn("queued", r.headers["location"])
        job = webapp.conn().execute("SELECT * FROM render_jobs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((job["range_start_utc"][:16], job["range_end_utc"][:16]), ("2026-11-19T08:30", "2026-11-19T09:45"))   # Denver (MST, UTC-7)
        bad = self.c.post("/renders", headers=h, data={"kind": "custom", "start": "2026-11-19T05:00", "end": "2026-11-19T04:00"}, follow_redirects=False)
        self.assertIn("invalid", bad.headers["location"])

    def test_renders_form_has_default_fps(self):
        import re as _re
        for url in ("/renders", "/renders?start=2026-11-19T01:00&fps=15", "/renders?fps=0"):
            t = self.c.get(url, headers=AUTH).text
            self.assertRegex(t, r'name="fps" value="\d+"')
        self.assertIn('name="fps" value="15"', self.c.get("/renders?fps=15", headers=AUTH).text)

    def test_nav_tabs_lightbox_and_no_inline_handlers(self):
        import re as _re
        self._seed(3)
        lib = self.c.get("/library?day=2026-11-19", headers=AUTH).text

        main_nav = _re.search(r'<nav aria-label="Main">(.*?)</nav>', lib, _re.S).group(1)
        self.assertNotIn(">Play<", main_nav); self.assertIn(">Settings<", main_nav); self.assertNotIn(">Camera<", main_nav); self.assertNotIn(">Maintenance<", main_nav)
        self.assertNotIn(">Live<", main_nav); self.assertNotIn(">Storage<", main_nav); self.assertIn(">Renders<", main_nav)
        self.assertIn('aria-label="Library"', lib); self.assertIn('data-lb="image"', lib)
        for url, label in (("/play", "Library"), ("/camera", "Settings"), ("/storage", "Settings"), ("/archive", "Settings"), ("/alerts", "Settings"), ("/maintenance", "Settings"), ("/settings", "Settings")):
            t = self.c.get(url, headers=AUTH).text
            self.assertIn(f'aria-label="{label}"', t, url)
            self.assertEqual(len(_re.findall(r'class="on" aria-current="page"', t)), 2, url)   # one active top item + one active tab
        self.assertEqual(len(_re.findall(r'class="on" aria-current="page"', self.c.get("/library?tab=videos", headers=AUTH).text)), 2)
        self.assertIn("/camera", self.c.get("/settings", headers=AUTH).text)
        for url in ("/", "/live", "/library", "/library?tab=videos", "/play", "/storage", "/renders", "/sessions", "/camera", "/settings", "/archive", "/alerts", "/maintenance"):
            self.assertIsNone(_re.search(r"<[a-z][^>]*\son[a-z]+\s*=", self.c.get(url, headers=AUTH).text), url)   # CSP: no inline handlers anywhere

    def test_overview_cleanups_strip_and_grouped_audit(self):
        from timecanvas.web import app as webapp
        c, _ = self._seed(5)
        c.execute("DELETE FROM health_events")
        old = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000000Z"); new = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        c.execute("INSERT INTO health_events(ts_utc,level,source,message) VALUES(?,?,?,?)", (old, "error", "camera", "camera offline OLDONE"))
        c.execute("INSERT INTO health_events(ts_utc,level,source,message) VALUES(?,?,?,?)", (new, "error", "camera", "camera offline NEWONE"))
        for i in range(30): c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", ("2026-11-20T00:11:17.000000Z", "cleanup", "delete", f"/x/{i}.jpg"))
        c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", ("2026-11-20T00:18:33.000000Z", "admin", "camera.mode", "1920x1080@30")); c.commit()
        t = self.c.get("/", headers=AUTH).text
        self.assertIn("NEWONE", t); self.assertNotIn("OLDONE", t); self.assertIn("1 older event", t)
        m = self.c.get("/maintenance", headers=AUTH).text
        self.assertEqual(m.count("cleanup</td>"), 1); self.assertIn("and 29 more like it", m)
        lib = self.c.get("/library?day=2026-11-19", headers=AUTH).text
        import re as _r2
        self.assertEqual(len(_r2.findall(r'title="\d\d:00: \d+ frame', lib)), 24); self.assertGreaterEqual(lib.count('class="gap"'), 19)   # 5 frames land in at most 5 hours
        self.assertIn("tfrom=00:00&amp;tto=01:00", lib.replace("&tto", "&amp;tto")); self.assertNotIn("tto=24:00", lib)
        st = self.c.get("/storage?month=2026-11", headers=AUTH).text
        self.assertEqual(st.count("<tr>"), st.count("</tr>")); self.assertNotIn("2026-11-01</a>", st); self.assertIn("2026-11-19</a>", st)   # empty days collapsed
        c.execute("INSERT INTO render_jobs(kind,range_start_utc,range_end_utc,params_json,created_utc) VALUES('custom','2026-11-19T07:00:00.000000Z','2026-11-19T09:00:00.000000Z','{}','x')"); c.commit()
        self.assertIn("2026-11-19 00:00:00 → 2026-11-19 02:00:00", self.c.get("/partials/renders", headers=AUTH).text)   # local, not UTC
        c.execute("DELETE FROM render_jobs"); c.execute("DELETE FROM health_events"); c.execute("DELETE FROM audit_events"); c.commit()   # shared DB: leave nothing behind

    def test_archive_page_settings_and_run(self):
        t = self.c.get("/archive", headers=AUTH).text
        self.assertIn("Not set up", t); self.assertIn("archive-setup.sh", t); self.assertIn('name="remote"', t)
        h = self._h()
        self.assertEqual(self.c.post("/archive/settings", headers=AUTH, data={"remote": "x:y"}).status_code, 403)          # CSRF
        bad = self.c.post("/archive/settings", headers=h, data={"remote": "-evil:../x", "enabled": "on"}, follow_redirects=False)
        self.assertIn("invalid", bad.headers["location"])
        ok = self.c.post("/archive/settings", headers=h, data={"remote": "tcarchive:Cam Archive", "enabled": "on", "hold": "on"}, follow_redirects=False)
        self.assertIn("saved", ok.headers["location"])
        t = self.c.get("/archive", headers=AUTH).text
        self.assertIn('value="tcarchive:Cam Archive"', t); self.assertRegex(t, r'name="enabled" checked')
        r = self.c.post("/archive/run", headers=h, follow_redirects=False)
        self.assertIn("could", r.headers["location"])                                                                       # no helper socket in tests
        self.c.post("/archive/settings", headers=h, data={"remote": "tcarchive:TimeCanvas"})                                 # leave defaults, shared DB
        from timecanvas.web import app as webapp
        wc = webapp.conn(); wc.execute("DELETE FROM settings WHERE key LIKE 'archive_%'"); wc.commit()

    def test_alerts_page_settings_secrets_and_test(self):
        from timecanvas.web import app as webapp
        h = self._h(); hook = "https://prod-7.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=TOPSECRETSIG"
        t = self.c.get("/alerts", headers=AUTH).text
        self.assertIn("Camera offline", t); self.assertIn('name="teams_webhook"', t); self.assertIn("docs/ALERTS.md", t)
        base = {"alerts_enabled": "on", "alert_stale_minutes": "10", "alert_offline_minutes": "3", "alert_remind_hours": "6", "alert_smtp_port": "587", "alert_smtp_security": "starttls"}
        post = lambda **kw: self.c.post("/alerts/settings", headers=h, data={**base, **kw}, follow_redirects=False).headers["location"]
        self.assertEqual(self.c.post("/alerts/settings", headers=AUTH, data=base).status_code, 403)                       # CSRF
        self.assertIn("invalid", post(teams_webhook="https://evil.example.com/x"))                                          # host allowlist
        self.assertIn("invalid", post(teams_webhook="http://prod.logic.azure.com/x"))
        self.assertIn("invalid", post(alert_stale_minutes="1"))                                                             # range
        self.assertIn("invalid", post(alert_teams_on="on"))                                                                 # on without a URL
        self.assertIn("invalid", post(alert_email_on="on"))                                                                 # email without server/from/to
        self.assertIn("invalid", post(alert_mail_to="not-an-address"))
        self.assertIn("saved", post(alert_teams_on="on", teams_webhook=hook, alert_on_disk="on", alert_on_camera_offline="on"))
        t = self.c.get("/alerts", headers=AUTH).text
        self.assertNotIn("TOPSECRETSIG", t); self.assertNotIn("logic.azure.com/workflows", t); self.assertIn("saved - leave blank to keep", t)   # never shown back
        self.assertEqual(oct(os.stat(webapp.alerts.SECRETS).st_mode & 0o777), "0o600")
        self.assertIn("TOPSECRETSIG", open(webapp.alerts.SECRETS).read())
        wc = webapp.conn(); aud = " ".join(r[0] for r in wc.execute("SELECT detail FROM audit_events WHERE action='alerts.settings'")); self.assertNotIn("TOPSECRETSIG", aud)   # not in the audit log
        self.assertEqual(wc.execute("SELECT value FROM settings WHERE key='alert_on_service'").fetchone()[0], "0")          # unticked rule saved as off
        with mock.patch.object(webapp.alerts, "send_teams", lambda m, **k: None):
            r = self.c.post("/alerts/test", headers=h, follow_redirects=False)
        self.assertIn("teams", r.headers["location"]); self.assertIn("delivered", r.headers["location"])
        with mock.patch.object(webapp.alerts, "send_teams", lambda m, **k: (_ for _ in ()).throw(RuntimeError("down"))):
            self.assertIn("FAILED", self.c.post("/alerts/test", headers=h, follow_redirects=False).headers["location"])
        self.assertIn("saved", post(alert_teams_on="", clear_teams="on")); self.assertNotIn("teams_webhook", webapp.alerts.load_secrets())
        pk = {"alert_email_method": "postal", "alert_postal_url": "https://postal.example.com", "alert_mail_from": "tc@example.com", "alert_mail_to": "me@example.com"}
        self.assertIn("invalid", post(alert_email_on="on", **pk))                                                           # Postal on without a key
        self.assertIn("invalid", post(alert_email_on="on", **{**pk, "alert_postal_url": "http://postal.example.com"}, postal_api_key="PKEY12345678"))   # secret-scan: allow (fake test key)
        self.assertIn("invalid", post(**{**pk, "alert_postal_url": "https://10.0.0.5"}))
        self.assertIn("invalid", post(**pk, postal_api_key="bad key!"))
        self.assertIn("saved", post(alert_email_on="on", **pk, postal_api_key="PKEY12345678"))   # secret-scan: allow (fake test key)
        t = self.c.get("/alerts", headers=AUTH).text
        self.assertNotIn("PKEY12345678", t); self.assertIn('value="https://postal.example.com"', t); self.assertIn("saved - leave blank to keep", t)
        self.assertNotIn("PKEY12345678", " ".join(r[0] for r in wc.execute("SELECT detail FROM audit_events")))
        self.assertEqual(webapp.alerts.load_secrets()["postal_api_key"], "PKEY12345678")
        with mock.patch.object(webapp.alerts, "send_postal", lambda m, s, secrets=None, host=None: None):
            self.assertIn("email", self.c.post("/alerts/test", headers=h, follow_redirects=False).headers["location"])
        self.assertIn("saved", post(**pk, clear_postal="on")); self.assertNotIn("postal_api_key", webapp.alerts.load_secrets())
        # independent channel tests + tailnet heartbeat
        self.assertIn("saved", post(heartbeat_url="http://100.64.0.5:3001/api/push/tok?status=up&msg=OK"))               # Uptime Kuma on the tailnet is accepted
        self.assertIn("invalid", post(heartbeat_url="http://127.0.0.1:3001/x")); self.assertIn("invalid", post(heartbeat_url="http://169.254.169.254/x"))
        from urllib.parse import unquote_plus
        test = lambda ch: unquote_plus(self.c.post("/alerts/test", headers=h, data={"channel": ch}, follow_redirects=False).headers["location"])
        self.assertIn("no teams webhook", test("teams").lower())                                                        # not saved -> clear message, nothing sent
        with mock.patch.object(webapp.alerts, "ping_heartbeat", lambda u: 200):
            self.assertIn("pinged", test("heartbeat"))
        self.assertIn("saved", post(teams_webhook=hook))                                                                       # saved but switch off
        with mock.patch.object(webapp.alerts, "send_teams", lambda m, **k: None), mock.patch.object(webapp.alerts, "send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Postal answered HTTP 403: error code: 1010"))):
            loc = test("teams"); self.assertIn("teams: OK", loc); self.assertNotIn("email", loc)
            loc = test("email"); self.assertIn("email: FAILED", loc); self.assertIn("1010", loc); self.assertNotIn("teams", loc)
        wc.execute("DELETE FROM settings WHERE key LIKE 'alert%'"); wc.execute("DELETE FROM alert_log"); wc.execute("DELETE FROM audit_events"); wc.commit()

    def test_edit_render_jobs_and_sessions(self):
        from timecanvas.web import app as webapp
        wc = webapp.conn(); wc.execute("DELETE FROM render_jobs"); wc.execute("DELETE FROM sessions"); wc.commit(); h = self._h()
        form = {"kind": "custom", "start": "2026-11-19T01:30", "end": "2026-11-19T02:45", "fps": "20", "crf": "23", "preset": "medium", "rotate": "0", "format": "mp4"}
        self.c.post("/renders", headers=h, data=form)
        jid = wc.execute("SELECT id FROM render_jobs").fetchone()[0]
        t = self.c.get(f"/renders?edit={jid}", headers=AUTH).text                                                           # prefilled with the job's own values, in local time
        self.assertIn('value="2026-11-19T01:30"', t); self.assertIn('value="2026-11-19T02:45"', t); self.assertIn('name="fps" value="20"', t); self.assertIn("Save and queue again", t)
        self.assertIn(f"/renders?edit={jid}", self.c.get("/partials/renders", headers=AUTH).text)
        r = self.c.post("/renders", headers=h, data={**form, "fps": "30", "end": "2026-11-19T03:00", "edit_id": str(jid)}, follow_redirects=False)
        self.assertIn("updated", r.headers["location"])                                                                     # queued job edited in place
        row = wc.execute("SELECT * FROM render_jobs").fetchall(); self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["range_end_utc"][:16], json.loads(row[0]["params_json"])["fps"], row[0]["status"]), ("2026-11-19T10:00", 30, "queued"))
        wc.execute("UPDATE render_jobs SET status='running'"); wc.commit()
        self.assertIn("invalid", self.c.post("/renders", headers=h, data={**form, "edit_id": str(jid)}, follow_redirects=False).headers["location"])   # not while running
        wc.execute("UPDATE render_jobs SET status='done'"); wc.commit()
        self.assertIn("Save as new job", self.c.get(f"/renders?edit={jid}", headers=AUTH).text)
        r = self.c.post("/renders", headers=h, data={**form, "fps": "12", "edit_id": str(jid)}, follow_redirects=False)
        self.assertEqual(wc.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0], 2)                                    # finished job kept, edit became a new job
        self.assertEqual(self.c.get("/renders?edit=99999", headers=AUTH).status_code, 200)
        # sessions
        sf = {"name": "weekdays", "start": "2026-11-01T00:00", "end": "", "interval": "60", "days": "0,1,2", "hours": "8,17"}
        self.c.post("/sessions", headers=h, data=sf); sid = wc.execute("SELECT id FROM sessions").fetchone()[0]
        t = self.c.get(f"/sessions?edit={sid}", headers=AUTH).text
        self.assertIn('value="weekdays"', t); self.assertIn('value="0,1,2"', t); self.assertIn('value="8,17"', t); self.assertIn("Save changes", t)
        self.assertIn("updated", self.c.post("/sessions", headers=h, data={**sf, "name": "renamed", "interval": "30", "edit_id": str(sid)}, follow_redirects=False).headers["location"])
        r = wc.execute("SELECT * FROM sessions").fetchall(); self.assertEqual((len(r), r[0]["name"], r[0]["interval_seconds"]), (1, "renamed", 30))
        self.assertIn("invalid", self.c.post("/sessions", headers=h, data={**sf, "interval": "5", "edit_id": str(sid)}, follow_redirects=False).headers["location"])
        wc.execute("DELETE FROM render_jobs"); wc.execute("DELETE FROM sessions"); wc.execute("DELETE FROM audit_events"); wc.commit()

    def test_live_page(self):
        t = self.c.get("/live", headers=AUTH).text
        self.assertIn("/live/stream", t); self.assertIn('id="fs"', t)

    def test_no_command_surface(self):
        routes = {r.path for r in self.c.app.routes}
        for bad in ("/exec", "/shell", "/sql", "/files", "/systemctl", "/ffmpeg"):
            self.assertNotIn(bad, routes)


if __name__ == "__main__":
    unittest.main()
