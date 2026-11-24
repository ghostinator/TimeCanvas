import os, sqlite3, sys, tempfile, unittest
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from timecanvas import capture, db, jpeg, paths

MIG = os.path.join(os.path.dirname(__file__), "..", "migrations")


def make_jpeg(w=1280, h=720):
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8\xff\xe0\x00\x04\x00\x00" + sof + b"\xff\xda\x00\x02" + b"\x00" * 200 + b"\xff\xd9"


GOOD = {"X-UStreamer-Online": "true", "X-UStreamer-Grab-Timestamp": "100.0", "X-UStreamer-Expose-Begin-Timestamp": "100.1"}


class T(unittest.TestCase):
    def test_jpeg(self):
        self.assertEqual(jpeg.inspect(make_jpeg()), (1280, 720))
        self.assertEqual(jpeg.inspect(make_jpeg() + b"\x00"), (1280, 720))  # camera padding after EOI
        for bad in (b"", b"garbage" * 50, make_jpeg()[:-2], make_jpeg()[:50]):
            with self.assertRaises(ValueError):
                jpeg.inspect(bad)

    def test_validate_rejects_placeholder_and_stale_and_wrong_size(self):
        self.assertEqual(capture.validate_snapshot(GOOD, make_jpeg(), 1280, 720, 5), (1280, 720))
        with self.assertRaises(ValueError): capture.validate_snapshot({**GOOD, "X-UStreamer-Online": "false"}, make_jpeg(), 1280, 720, 5)
        with self.assertRaises(ValueError): capture.validate_snapshot({**GOOD, "X-UStreamer-Grab-Timestamp": "0.0"}, make_jpeg(), 1280, 720, 5)
        with self.assertRaises(ValueError): capture.validate_snapshot({**GOOD, "X-UStreamer-Expose-Begin-Timestamp": "200"}, make_jpeg(), 1280, 720, 5)
        with self.assertRaises(ValueError): capture.validate_snapshot(GOOD, make_jpeg(640, 480), 1280, 720, 5)
        # the streamer's own reported size wins over the config fallback (mode changes need no config edit)
        self.assertEqual(capture.validate_snapshot({**GOOD, "X-UStreamer-Width": "1920", "X-UStreamer-Height": "1080"}, make_jpeg(1920, 1080), 1280, 720, 5), (1920, 1080))
        with self.assertRaises(ValueError): capture.validate_snapshot({**GOOD, "X-UStreamer-Width": "1920", "X-UStreamer-Height": "1080"}, make_jpeg(1280, 720), 1280, 720, 5)

    def test_filename_offset_and_dst(self):
        n = capture.filename_for(datetime(2026, 11, 19, 16, 1, 30, tzinfo=timezone.utc), "America/Denver")
        self.assertEqual(n, "images/2026/11/19/2026-11-19T09-01-30-0700.jpg")
        # DST fall-back 2026-11-01: 07:30Z is 01:30 MDT(-0600); 08:30Z is 01:30 MST(-0700): names differ
        a = capture.filename_for(datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc), "America/Denver")
        b = capture.filename_for(datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc), "America/Denver")
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith("-0600.jpg") and b.endswith("-0700.jpg"))

    def test_slots_and_clamp(self):
        self.assertEqual(capture.slot_of(59.9, 30), capture.slot_of(30.0, 30))
        self.assertNotEqual(capture.slot_of(59.9, 30), capture.slot_of(60.0, 30))
        self.assertEqual((capture.clamp_interval(1), capture.clamp_interval(99999), capture.clamp_interval(30)), (10, 3600, 30))

    def test_session_schedule(self):
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row; db.migrate(c, MIG)
        now = datetime(2026, 11, 19, 16, 0, tzinfo=timezone.utc)  # Thu 09:00 Denver
        self.assertEqual(capture.active_session(c, now, "America/Denver"), (None, True))
        c.execute("insert into sessions(name,start_utc,end_utc,interval_seconds,schedule_json,created_utc) values('s','2026-11-01T00:00:00.000000Z',NULL,60,'{\"days\":[0,1],\"hours\":[8,17]}','t')")
        self.assertEqual(capture.active_session(c, now, "America/Denver"), (60, False))   # Thursday not allowed
        c.execute("update sessions set schedule_json='{\"days\":[3],\"hours\":[8,17]}'")
        self.assertEqual(capture.active_session(c, now, "America/Denver"), (60, True))
        c.execute("update sessions set schedule_json='{\"hours\":[10,17]}'")
        self.assertEqual(capture.active_session(c, now, "America/Denver"), (60, False))

    def test_thresholds(self):
        self.assertEqual([capture.disk_level(p, 80, 90) for p in (10, 79.9, 80, 89.9, 90, 100)],
                         ["ok", "ok", "warning", "warning", "critical", "critical"])

    def test_safe_path(self):
        with tempfile.TemporaryDirectory() as r:
            os.makedirs(f"{r}/images/a"); os.makedirs(f"{r}/outside")
            open(f"{r}/outside/x", "w").close()
            os.symlink(f"{r}/outside", f"{r}/images/link")
            ok = f"{r}/images/a/f.jpg"
            self.assertEqual(paths.safe_path(ok, r), os.path.realpath(ok))
            for bad in ("", "relative/x", "/", f"{r}/images/../outside/x", f"{r}/images/link/x", f"{r}/outside/x", "/etc/passwd", f"{r}/images\0x", None, f"{r}"):
                with self.assertRaises(ValueError, msg=repr(bad)): paths.safe_path(bad, r)

    def test_migrations_idempotent(self):
        c = sqlite3.connect(":memory:")
        db.migrate(c, MIG); db.migrate(c, MIG)
        names = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        for t in ("settings", "camera_capabilities", "camera_profiles", "capture_events", "media_files", "sessions", "render_jobs", "health_events", "pinned_media", "audit_events"):
            self.assertIn(t, names)
        import glob
        self.assertEqual(c.execute("select count(*) from schema_migrations").fetchone()[0], len(glob.glob(os.path.join(MIG, "[0-9]*.sql"))))


if __name__ == "__main__":
    unittest.main()
