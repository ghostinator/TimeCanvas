import os, sqlite3, sys, tempfile, unittest, zipfile
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from timecanvas import db, files, render
from test_core import MIG, make_jpeg

T0 = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)  # local midnight in Denver


def setup(r, n=6):
    for d in ("images", "videos/daily", "tmp"):
        os.makedirs(f"{r}/{d}", exist_ok=True)
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    db.migrate(c, MIG)
    for i in range(n):
        p = f"{r}/images/f{i}.jpg"
        open(p, "wb").write(make_jpeg()); add(c, p, T0 + timedelta(minutes=i))
    return c


def add(c, p, ts, typ="image", dur=None):
    c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc,duration) VALUES(?,?,?,?,?,?,?,?,?)",
              (p, typ, ts.strftime(render.TS), "America/Denver", 1280, 720, os.path.getsize(p) if os.path.exists(p) else 1, "x", dur))
    c.commit()
    return c.execute("select last_insert_rowid()").fetchone()[0]


class F(unittest.TestCase):
    def test_range_rows_bounds_and_pinned_flag(self):
        with tempfile.TemporaryDirectory() as r:
            c = setup(r)
            c.execute("INSERT INTO pinned_media VALUES(2,'t',NULL)")
            rows = files.range_rows(c, T0, T0 + timedelta(minutes=3))   # [0,3) -> f0,f1,f2
            self.assertEqual([x["path"].rsplit("/", 1)[1] for x in rows], ["f0.jpg", "f1.jpg", "f2.jpg"])
            self.assertEqual([x["pinned"] for x in rows], [0, 1, 0])
            self.assertEqual(len(files.range_rows(c, T0, T0 + timedelta(minutes=3), include_pinned=False)), 2)

    def test_deletable_excludes_pinned_protected_and_active_render(self):
        with tempfile.TemporaryDirectory() as r:
            c = setup(r)
            c.execute("INSERT INTO pinned_media VALUES(1,'t',NULL)")
            c.execute("UPDATE media_files SET protected=1 WHERE id=2")
            c.execute("INSERT INTO render_jobs(kind,range_start_utc,range_end_utc,params_json,status,created_utc) VALUES('custom',?,?,'{}','running','t')",
                      ((T0 + timedelta(minutes=3)).strftime(render.TS), (T0 + timedelta(minutes=5)).strftime(render.TS)))
            ok, pinned, busy = files.deletable(c, files.range_rows(c, T0, T0 + timedelta(hours=1)))
            self.assertEqual((pinned, busy), (2, 2))
            self.assertEqual(sorted(x["path"].rsplit("/", 1)[1] for x in ok), ["f2.jpg", "f5.jpg"])   # id1=f0 pinned, id2=f1 protected, f3/f4 inside the running render

    def test_bulk_delete_removes_only_deletable_and_audits(self):
        with tempfile.TemporaryDirectory() as r:
            c = setup(r)
            c.execute("INSERT INTO pinned_media VALUES(1,'t',NULL)")
            res = files.bulk_delete(c, r, files.range_rows(c, T0, T0 + timedelta(hours=1)), "test")
            self.assertEqual(res, {"deleted": 5, "failed": 0, "skipped_pinned": 1, "skipped_render": 0})
            self.assertEqual(sorted(os.listdir(f"{r}/images")), ["f0.jpg"])
            self.assertEqual(c.execute("select count(*) from audit_events where action='delete'").fetchone()[0], 5)
            self.assertEqual(c.execute("select count(*) from media_files where status='deleted'").fetchone()[0], 5)

    def test_zip_contents_symlink_escape_and_caps(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as out:
            c = setup(r, 3)
            secret = os.path.join(out, "secret.jpg"); open(secret, "wb").write(b"top secret")  # secret-scan: allow (dummy fixture)
            os.symlink(secret, f"{r}/images/evil.jpg")
            add(c, f"{r}/images/evil.jpg", T0 + timedelta(minutes=9))      # DB row pointing at a symlink that escapes the root
            z = files.build_zip(r, files.range_rows(c, T0, T0 + timedelta(hours=1)), tmpdir=out)
            with zipfile.ZipFile(z) as zf:
                names = sorted(zf.namelist())
                self.assertEqual(names, ["f0.jpg", "f1.jpg", "f2.jpg"])     # evil.jpg skipped, never followed
                self.assertTrue(all(b"top secret" not in zf.read(n) for n in names))
            old = files.ZIP_MAX_FILES; files.ZIP_MAX_FILES = 2
            try:
                with self.assertRaises(ValueError): files.build_zip(r, files.range_rows(c, T0, T0 + timedelta(hours=1)), tmpdir=out)
            finally:
                files.ZIP_MAX_FILES = old
            with self.assertRaises(ValueError): files.build_zip(r, [], tmpdir=out)

    def test_day_stats_on_dst_days(self):
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row; db.migrate(c, MIG)
        fall = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)   # 00:00 MDT; the local day is 25 h long
        for h in (0, 24):
            add(c, f"/x/{h}", fall + timedelta(hours=h) - timedelta(seconds=1 if h else 0))
        add(c, "/x/next", fall + timedelta(hours=25))               # first instant of the next local day
        self.assertEqual(files.day_stats(c, date(2026, 11, 1), "America/Denver")["frames"], 2)
        self.assertEqual(files.day_stats(c, date(2026, 11, 2), "America/Denver")["frames"], 1)


if __name__ == "__main__":
    unittest.main()
