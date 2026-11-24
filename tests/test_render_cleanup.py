import json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from timecanvas import cleanup, db, reconcile, render
from test_core import MIG, make_jpeg


HAS_SUBS = bool(shutil.which("ffmpeg")) and b" subtitles " in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True).stdout


def mkdb():
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    db.migrate(c, MIG)
    return c


def add(c, path, ts, typ="image", **kw):
    c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)",
              (path, typ, ts.strftime(render.TS), "America/Denver", 1280, 720, 10, "x"))
    return c.execute("select last_insert_rowid()").fetchone()[0]


class R(unittest.TestCase):
    def test_day_range_dst(self):
        s, e = render.day_range(date(2026, 11, 1), "America/Denver")  # fall back: 25 h
        self.assertEqual((e - s), timedelta(hours=25))
        s, e = render.day_range(date(2026, 3, 8), "America/Denver")   # spring forward: 23 h
        self.assertEqual((e - s), timedelta(hours=23))
        s, e = render.day_range(date(2026, 11, 19), "America/Denver")
        self.assertEqual(s, datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc))

    def test_parse_local_times_and_whole_days(self):
        tz = "America/Denver"
        self.assertEqual(render.parse_local("2026-11-19T07:30", tz), datetime(2026, 11, 19, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(render.parse_local("2026-11-19", tz), datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(render.parse_local("2026-11-19", tz, end=True), datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc))
        with self.assertRaises(ValueError): render.parse_local("2026-11-19T25:00", tz)
        with self.assertRaises(ValueError): render.validate_params({"format": "gif"})

    def test_param_validation(self):
        self.assertEqual(render.validate_params({})["fps"], 30)
        for bad in ({"fps": 0}, {"fps": 999}, {"crf": 5}, {"preset": "x; rm -rf /"}, {"rotate": 45}, {"crop": [1, 2, 3]}, {"scale": [8, 8]}, {"crop": ["a", 1, 1, 1]}):
            with self.assertRaises(ValueError, msg=str(bad)): render.validate_params(bad)

    def test_filter_chain_normalises_sizes_and_even_dims(self):
        vf, w, h = render.filter_chain(render.validate_params({"scale": [641, 361]}), 1280, 720)
        self.assertEqual((w, h), (640, 360)); self.assertIn("pad=640:360", vf); self.assertTrue(vf.endswith("format=yuv420p"))
        _, w, h = render.filter_chain(render.validate_params({"rotate": 90}), 1280, 720)
        self.assertEqual((w, h), (720, 1280))

    def test_concat_order_is_explicit_and_quoted(self):
        t = render.concat_text(["/a/2.jpg", "/a/it's.jpg"], 30)
        lines = [l for l in t.splitlines() if l.startswith("file")]
        self.assertEqual(lines[0], "file /a/2.jpg"); self.assertIn("'\"'\"'", lines[1])

    def test_select_frames_orders_by_utc_not_name(self):
        with tempfile.TemporaryDirectory() as r:
            os.makedirs(f"{r}/images")
            c = mkdb()
            t0 = datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)
            # DST fall-back: 01:30-0600 (07:30Z) sorts AFTER 01:30-0700 (08:30Z) by name, but must come first by UTC
            for name, t in (("2026-11-01T01-30-00-0700.jpg", t0 + timedelta(hours=1)), ("2026-11-01T01-30-00-0600.jpg", t0)):
                open(f"{r}/images/{name}", "wb").write(make_jpeg()); add(c, f"{r}/images/{name}", t)
            got = [os.path.basename(p) for p, _ in render.select_frames(c, t0 - timedelta(hours=1), t0 + timedelta(hours=3), r)]
            self.assertEqual(got, ["2026-11-01T01-30-00-0600.jpg", "2026-11-01T01-30-00-0700.jpg"])

    def test_job_idempotency(self):
        c = mkdb(); s = datetime(2026, 11, 1, tzinfo=timezone.utc); e = s + timedelta(days=1)
        a = render.create_job(c, "daily", s, e, {}); b = render.create_job(c, "daily", s, e, {})
        self.assertEqual(a, b)
        c.execute("update render_jobs set status='failed' where id=?", (a,))
        self.assertEqual(render.create_job(c, "daily", s, e, {}), a)
        self.assertEqual(c.execute("select status from render_jobs").fetchone()[0], "queued")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
    def test_end_to_end_render_and_cancel_leave_no_false_complete(self):
        with tempfile.TemporaryDirectory() as r:
            for d in ("images", "videos/daily", "tmp", "thumbnails"): os.makedirs(f"{r}/{d}")
            c = mkdb(); t0 = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)
            for i in range(12):
                p = f"{r}/images/f{i:02d}.jpg"
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{i*20:02x}4080:s=320x240", "-frames:v", "1", p], check=True)
                c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,created_utc) VALUES(?,?,?,?,?,?,?,?)",
                          (p, "image", (t0 + timedelta(seconds=30 * i)).strftime(render.TS), "America/Denver", 320, 240, 1, "x"))
            cfg = {"storage": {"root": r}, "timezone": "America/Denver"}
            jid = render.create_job(c, "daily", t0, t0 + timedelta(hours=1), {"fps": 10, "overlay": HAS_SUBS, "preset": "ultrafast"})
            render.run_job(c, jid, cfg)
            j = c.execute("select * from render_jobs where id=?", (jid,)).fetchone()
            self.assertEqual(j["status"], "done", j["error"]); out = c.execute("select path from media_files where id=?", (j["output_media_id"],)).fetchone()[0]
            info = render.probe(out); self.assertEqual((info["codec_name"], info["pix_fmt"]), ("h264", "yuv420p"))
            self.assertEqual(info["nb_frames"], "12")   # exactly the frames selected (concat+-r used to emit one extra)
            self.assertEqual(os.listdir(f"{r}/tmp"), [])
            self.assertEqual(len(os.listdir(f"{r}/images")), 12)  # sources untouched
            if b"libwebp_anim" in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True).stdout:
                jw = render.create_job(c, "custom", t0, t0 + timedelta(hours=1), {"fps": 10, "format": "webp"})
                render.run_job(c, jw, cfg)
                w = c.execute("select * from render_jobs where id=?", (jw,)).fetchone()
                self.assertEqual(w["status"], "done", w["error"])
                self.assertTrue(c.execute("select path from media_files where id=?", (w["output_media_id"],)).fetchone()[0].endswith(".webp"))
            # cancelled-before-start style failure: empty range -> failed, nothing in videos
            before = len(os.listdir(f"{r}/videos/custom")) if os.path.isdir(f"{r}/videos/custom") else 0
            j2 = render.create_job(c, "custom", t0 + timedelta(days=5), t0 + timedelta(days=6), {})
            render.run_job(c, j2, cfg)
            self.assertEqual(c.execute("select status from render_jobs where id=?", (j2,)).fetchone()[0], "failed")
            self.assertEqual(len(os.listdir(f"{r}/videos/custom")) if os.path.isdir(f"{r}/videos/custom") else 0, before)


class C(unittest.TestCase):
    cfg = {"storage": {"frame_retention_days": 30, "video_retention_days": 365}}

    def test_plan_selection(self):
        c = mkdb(); now = datetime(2026, 11, 19, tzinfo=timezone.utc)
        old = now - timedelta(days=40); new = now - timedelta(days=5)
        a = add(c, "/x/old", old); b = add(c, "/x/new", new); p = add(c, "/x/pinned", old); q = add(c, "/x/active", old - timedelta(days=1))
        v = add(c, "/x/vid", old, "video"); ov = add(c, "/x/oldvid", now - timedelta(days=400), "video")
        c.execute("INSERT INTO pinned_media VALUES(?,?,NULL)", (p, "t"))
        c.execute("INSERT INTO render_jobs(kind,range_start_utc,range_end_utc,params_json,status,created_utc) VALUES('custom',?,?,'{}','running','t')",
                  ((old - timedelta(days=2)).strftime(render.TS), (old - timedelta(hours=1)).strftime(render.TS)))
        got = {x[1] for x in cleanup.plan(c, self.cfg, now)}
        self.assertEqual(got, {"/x/old", "/x/oldvid"})  # not new, pinned, active-render frames, or videos < 365d

    def test_delete_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as outside:
            os.makedirs(f"{r}/images"); victim = f"{outside}/victim"; open(victim, "w").write("keep")
            os.symlink(outside, f"{r}/images/link")
            c = mkdb()
            for bad in (victim, f"{r}/images/link/victim", "", "/", "relative", f"{r}/images/../../etc/passwd"):
                mid = add(c, bad or "empty", datetime(2020, 1, 1, tzinfo=timezone.utc))
                self.assertFalse(cleanup.delete_one(c, r, mid, bad, "t"), bad)
            self.assertTrue(os.path.exists(victim))
            good = f"{r}/images/g.jpg"; open(good, "wb").write(b"x"); mid = add(c, good, datetime(2020, 1, 1, tzinfo=timezone.utc))
            self.assertTrue(cleanup.delete_one(c, r, mid, good, "t")); self.assertFalse(os.path.exists(good))
            self.assertEqual(c.execute("select status from media_files where id=?", (mid,)).fetchone()[0], "deleted")
            self.assertGreaterEqual(c.execute("select count(*) from audit_events").fetchone()[0], 1)


class RC(unittest.TestCase):
    def test_parse_name(self):
        self.assertEqual(reconcile.parse_name("2026-11-19T09-01-30-0700.jpg", "x"), datetime(2026, 11, 19, 16, 1, 30, tzinfo=timezone.utc))
        self.assertIsNone(reconcile.parse_name("junk.jpg", "x"))


if __name__ == "__main__":
    unittest.main()
