import json, os, shutil, sqlite3, stat, sys, tempfile, unittest, zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["TIMECANVAS_MIGRATIONS"] = os.path.join(os.path.dirname(__file__), "..", "migrations")   # db binds this at import time
from timecanvas import archive, cleanup, db, locks, render
from test_core import MIG, make_jpeg

TZ = "America/Denver"
FAKE = '''#!/usr/bin/env python3
import json, os, shutil, sys
a = sys.argv[1:]
assert a[0] == "--config"; a = a[2:]
R = os.environ["FAKE_REMOTE"]
def loc(p): return os.path.join(R, p.split(":", 1)[1].lstrip("/"))
if a[0] == "listremotes": print("tcarchive:")
elif a[0] == "copyto":
    if os.environ.get("FAKE_FAIL"): sys.stderr.write("boom: token expired"); sys.exit(1)
    d = loc(a[2]); os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copyfile(a[1], d)
    if os.environ.get("FAKE_TRUNCATE"): open(d, "r+b").truncate(3)
elif a[0] == "lsjson":
    d = loc(a[1]); print(json.dumps([{"Name": os.path.basename(d), "Size": os.path.getsize(d)}]))
'''


def mkdb():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    db.migrate(c, MIG); return c


class A(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.root = self.tmp + "/srv"; self.remote = self.tmp + "/onedrive"
        for d in ("images", "videos/custom", "tmp"): os.makedirs(f"{self.root}/{d}")
        os.makedirs(self.remote)
        bin_ = self.tmp + "/rclone"; open(bin_, "w").write(FAKE); os.chmod(bin_, 0o755)
        env = {"FAKE_REMOTE": self.remote}
        self.p = [mock.patch.object(archive, "RCLONE", bin_), mock.patch.object(archive, "CONF", self.tmp + "/rclone.conf"), mock.patch.dict(os.environ, env), mock.patch.object(locks, "DIR", self.tmp + "/run")]
        [p.start() for p in self.p]; self.addCleanup(lambda: [p.stop() for p in self.p]); self.addCleanup(shutil.rmtree, self.tmp)
        self.c = mkdb(); self.c.execute("INSERT INTO settings(key,value,updated_utc) VALUES('archive_enabled','1','x')"); self.c.commit()
        self.cfg = {"storage": {"root": self.root, "db": ":memory:", "frame_retention_days": 30, "video_retention_days": 365, "disk_critical_percent": 90, "disk_warning_percent": 80},
                    "timezone": TZ, "capture": {"interval_seconds": 30}}
        self.today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(TZ)).date()

    def frame(self, day, hour=12, n=1):
        s, _ = render.day_range(day, TZ)
        for i in range(n):
            ts = s + timedelta(hours=hour, minutes=i)
            p = f"{self.root}/images/{ts:%Y%m%dT%H%M}.jpg"; open(p, "wb").write(make_jpeg())
            self.c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)", (p, "image", ts.strftime(render.TS), TZ, 8, 8, os.path.getsize(p), "x"))
        self.c.commit()

    def run_archive(self):
        # run() opens its own connection from cfg; hand it ours
        with mock.patch.object(archive.db, "connect", lambda *_: self.c), mock.patch.object(archive.os.path, "ismount", lambda _: True):
            return archive.run(self.cfg)

    def test_remote_validation(self):
        for ok in ("tcarchive:TimeCanvas", "tcarchive:", "a-b_c:My Folder/sub.dir"):
            self.assertTrue(archive.valid_remote(ok), ok)
        for bad in ("", "tcarchive", "-evil:x", "x:../up", "x:a/../b", "x:a;rm", "x:$(id)", "x:" + "a" * 101, "x y:z", ":x"):
            self.assertFalse(archive.valid_remote(bad), bad)

    def test_finished_days_zipped_today_untouched_videos_uploaded_and_idempotent(self):
        d1, d2 = self.today - timedelta(days=2), self.today - timedelta(days=1)
        self.frame(d1, n=3); self.frame(d2, n=2); self.frame(self.today, n=1)
        v = f"{self.root}/videos/custom/custom-1.mp4"; open(v, "wb").write(b"x" * 500)
        self.c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)", (v, "video", "2026-01-01T00:00:00.000000Z", TZ, 8, 8, 500, "x")); self.c.commit()
        self.assertEqual(self.run_archive(), 0)
        z1 = f"{self.remote}/TimeCanvas/frames/{d1:%Y}/{d1:%m}/{d1}.zip"
        with zipfile.ZipFile(z1) as z:
            names = z.namelist(); man = json.loads(z.read("manifest.json"))
        self.assertEqual(len(names), 4); self.assertEqual(man["frames"], 3); self.assertEqual(man["day"], d1.isoformat())
        self.assertTrue(os.path.exists(f"{self.remote}/TimeCanvas/videos/custom-1.mp4"))
        self.assertFalse(os.path.exists(f"{self.remote}/TimeCanvas/frames/{self.today:%Y}/{self.today:%m}/{self.today}.zip"))   # today is not finished
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM archive_items WHERE status='ok'").fetchone()[0], 3)
        self.assertEqual(os.listdir(f"{self.root}/tmp"), [])                                                                   # temp zips cleaned
        self.assertEqual(len(os.listdir(f"{self.root}/images")), 6)                                                            # local files untouched
        mtime = os.path.getmtime(z1); self.assertEqual(self.run_archive(), 0); self.assertEqual(os.path.getmtime(z1), mtime)   # second run uploads nothing
        self.assertIn("already archived", json.loads(db.get_setting(self.c, "archive_status"))["msg"])

    def test_failure_stops_records_nothing_ok_and_cleans_up(self):
        self.frame(self.today - timedelta(days=1), n=2)
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}):
            self.assertEqual(self.run_archive(), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM archive_items").fetchone()[0], 0)
        st = json.loads(db.get_setting(self.c, "archive_status")); self.assertFalse(st["ok"]); self.assertIn("token expired", st["msg"])
        self.assertEqual(os.listdir(f"{self.root}/tmp"), [])
        self.assertEqual(len(archive.pending_days(self.c, TZ, self.today)), 1)       # still pending, retried next run

    def test_size_mismatch_is_not_marked_archived(self):
        self.frame(self.today - timedelta(days=1))
        with mock.patch.dict(os.environ, {"FAKE_TRUNCATE": "1"}):
            self.assertEqual(self.run_archive(), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM archive_items WHERE status='ok'").fetchone()[0], 0)
        self.assertIn("verification failed", json.loads(db.get_setting(self.c, "archive_status"))["msg"])

    def test_disabled_and_unconfigured_do_nothing_destructive(self):
        self.frame(self.today - timedelta(days=1))
        self.c.execute("UPDATE settings SET value='0' WHERE key='archive_enabled'"); self.c.commit()
        self.assertEqual(self.run_archive(), 0); self.assertEqual(os.listdir(self.remote), [])
        self.c.execute("UPDATE settings SET value='1' WHERE key='archive_enabled'"); self.c.commit()
        with mock.patch.object(archive, "configured", lambda _: False):
            self.assertEqual(self.run_archive(), 0)
        self.assertFalse(json.loads(db.get_setting(self.c, "archive_status"))["ok"]); self.assertEqual(os.listdir(self.remote), [])

    def test_retention_waits_for_the_archive_and_releases_when_disk_is_critical(self):
        old, newer = self.today - timedelta(days=40), self.today - timedelta(days=39)
        self.frame(old, n=2); self.frame(newer, n=2)
        self.c.execute("INSERT INTO archive_items(kind,key,status,archived_utc) VALUES('day',?,'ok','x')", (f"day:{old}",)); self.c.commit()
        ids = lambda: {m for m, _, _ in cleanup.plan(self.c, self.cfg)}
        self.assertEqual(len(ids()), 2)                                          # only the archived day is deletable
        self.c.execute("UPDATE settings SET value='0' WHERE key='archive_enabled'")
        self.assertEqual(len(ids()), 4)                                          # archive off: retention as before
        self.c.execute("UPDATE settings SET value='1' WHERE key='archive_enabled'"); self.c.execute("INSERT INTO settings(key,value,updated_utc) VALUES('archive_hold','0','x')"); self.c.commit()
        self.assertEqual(len(ids()), 4)                                          # hold switched off
        self.c.execute("UPDATE settings SET value='1' WHERE key='archive_hold'"); self.c.commit()
        full = mock.Mock(used=95, total=100)
        with mock.patch.object(archive.shutil, "disk_usage", lambda _: full):
            self.assertEqual(len(ids()), 4)                                      # disk critical: a stuck archive must not fill the disk

    def test_zip_skips_files_outside_the_media_root(self):
        d = self.today - timedelta(days=1); self.frame(d)
        outside = self.tmp + "/secret.jpg"; open(outside, "wb").write(b"nope")
        s, _ = render.day_range(d, TZ)
        self.c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)", (outside, "image", (s + timedelta(hours=13)).strftime(render.TS), TZ, 8, 8, 4, "x")); self.c.commit()
        n = archive.build_zip(self.c, self.root, d, TZ, self.tmp + "/t.zip")
        self.assertEqual(n, 1)
        self.assertNotIn("secret.jpg", zipfile.ZipFile(self.tmp + "/t.zip").namelist())


if __name__ == "__main__":
    unittest.main()
