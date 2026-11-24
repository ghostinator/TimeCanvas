"""Rendering: validated frame selection -> explicit ffmpeg concat list -> tmp mp4 -> ffprobe check -> atomic move -> DB."""
import hashlib, json, logging, os, re, shlex, signal, subprocess, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config as cfgmod, db, jpeg, locks, paths

log = logging.getLogger("timecanvas.render")
TS = "%Y-%m-%dT%H:%M:%S.%fZ"
DEFAULTS = {"fps": 30, "crf": 23, "preset": "medium", "crop": None, "scale": None, "rotate": 0, "overlay": False, "format": "mp4"}
PRESETS = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"}


def fmt(dt):
    return dt.astimezone(timezone.utc).strftime(TS)


def day_range(d, tz):
    """[start,end) UTC for local calendar day d (DST-safe: bounds come from local midnights)."""
    z = ZoneInfo(tz)
    s = datetime(d.year, d.month, d.day, tzinfo=z)
    e_d = d + timedelta(days=1)
    e = datetime(e_d.year, e_d.month, e_d.day, tzinfo=z)
    return s.astimezone(timezone.utc), e.astimezone(timezone.utc)


def parse_local(v, tz, end=False):
    """'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' (browser datetime-local) in local time -> UTC.
    A bare date means the whole day: start = local midnight, end = the next local midnight."""
    v = (v or "").strip()
    z = ZoneInfo(tz)
    if "T" in v:
        return datetime.strptime(v[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=z).astimezone(timezone.utc)
    s, e = day_range(date.fromisoformat(v), tz)
    return e if end else s


def validate_params(p):
    """Server-side validation; returns a clean dict or raises ValueError. No raw ffmpeg args ever pass through."""
    q = {**DEFAULTS, **(p or {})}
    q["fps"] = int(q["fps"]); q["crf"] = int(q["crf"]); q["rotate"] = int(q["rotate"])
    if not 1 <= q["fps"] <= 60: raise ValueError("fps 1-60")
    if not 14 <= q["crf"] <= 35: raise ValueError("crf 14-35")
    if q["preset"] not in PRESETS: raise ValueError("bad preset")
    if q["rotate"] not in (0, 90, 180, 270): raise ValueError("rotate 0/90/180/270")
    q["overlay"] = bool(q["overlay"])
    if q["format"] not in ("mp4", "webp"): raise ValueError("format mp4/webp")
    for k in ("crop", "scale"):
        if q[k]:
            if not (isinstance(q[k], (list, tuple)) and len(q[k]) == (4 if k == "crop" else 2) and all(isinstance(x, int) and 0 <= x <= 8192 for x in q[k])):
                raise ValueError(f"bad {k}")
            q[k] = list(q[k])
            if k == "scale" and (q[k][0] < 16 or q[k][1] < 16): raise ValueError("scale too small")
            if k == "crop" and (q[k][0] < 16 or q[k][1] < 16): raise ValueError("crop too small")
        else:
            q[k] = None
    return q


def concat_text(files, fps):
    out = ["ffconcat version 1.0"]
    for f in files:
        out.append("file " + shlex.quote(f))
        out.append(f"duration {1.0 / fps:.6f}")
    return "\n".join(out) + "\n"


def ass_text(stamps, fps, w, h):
    def t(i):
        s = i / fps
        return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BorderStyle,Outline,Alignment,MarginL,MarginV\n"
            f"Style: Default,DejaVu Sans,{max(14, h // 28)},&H00FFFFFF,&H00000000,1,2,1,16,12\n[Events]\n"
            "Format: Layer,Start,End,Style,Text\n")
    return head + "".join(f"Dialogue: 0,{t(i)},{t(i + 1)},Default,{s}\n" for i, s in enumerate(stamps))


def filter_chain(p, first_w, first_h, ass_path=None):
    f = []
    if p["crop"]:
        w, h, x, y = p["crop"]; f.append(f"crop={w}:{h}:{x}:{y}")
    if p["rotate"]:
        f.append({90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}[p["rotate"]])
    if p["scale"]:
        w, h = p["scale"]
    elif p["crop"]:
        w, h = p["crop"][0], p["crop"][1]
        if p["rotate"] in (90, 270): w, h = h, w
    else:
        w, h = (first_h, first_w) if p["rotate"] in (90, 270) else (first_w, first_h)
    w -= w % 2; h -= h % 2
    f.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")  # normalise mixed sizes
    if p["overlay"] and ass_path:
        f.append("subtitles='" + ass_path.replace("'", "") + "'")  # tmp path we generate; quotes stripped defensively
    f.append("scale=in_range=full:out_range=tv,format=yuv420p")  # JPEG (full range) -> real yuv420p, not yuvj420p
    return ",".join(f), w, h


def select_frames(c, start_utc, end_utc, root):
    rows = c.execute("SELECT id,path,ts_utc,tz,width,height FROM media_files WHERE media_type='image' AND status='ok' "
                     "AND ts_utc>=? AND ts_utc<? ORDER BY ts_utc, id", (fmt(start_utc), fmt(end_utc))).fetchall()
    ok = []
    for r in rows:
        try:
            p = paths.safe_path(r["path"], root)
        except ValueError:
            continue
        if os.path.isfile(p):
            ok.append((p, r))
    return ok


def job_key(kind, s, e, params):
    return hashlib.sha256(json.dumps([kind, fmt(s), fmt(e), params], sort_keys=True).encode()).hexdigest()[:32]


def create_job(c, kind, s, e, params, rerender=False):
    p = validate_params(params)
    key = job_key(kind, s, e, p)
    r = c.execute("SELECT id,status FROM render_jobs WHERE idempotency_key=?", (key,)).fetchone()
    if r:
        if r["status"] in ("queued", "running") or (r["status"] == "done" and not rerender):
            return r["id"]
        c.execute("UPDATE render_jobs SET status='queued',progress=0,error=NULL,pid=NULL,started_utc=NULL,completed_utc=NULL WHERE id=?", (r["id"],))
        c.commit()
        return r["id"]
    cur = c.execute("INSERT INTO render_jobs(kind,range_start_utc,range_end_utc,params_json,idempotency_key,created_utc) VALUES(?,?,?,?,?,?)",
                    (kind, fmt(s), fmt(e), json.dumps(p), key, db.utcnow()))
    c.commit()
    return cur.lastrowid


def probe(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,pix_fmt,width,height,nb_frames:format=duration", "-of", "json", path],
                       capture_output=True, text=True, timeout=60)
    j = json.loads(o.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    return {**s, "duration": float(j.get("format", {}).get("duration", 0) or 0)}


def set_job(c, jid, **kw):
    c.execute("UPDATE render_jobs SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), jid))
    c.commit()


def run_job(c, jid, cfg):
    root = cfg["storage"]["root"]
    job = c.execute("SELECT * FROM render_jobs WHERE id=?", (jid,)).fetchone()
    p = validate_params(json.loads(job["params_json"]))
    s = datetime.strptime(job["range_start_utc"], TS).replace(tzinfo=timezone.utc)
    e = datetime.strptime(job["range_end_utc"], TS).replace(tzinfo=timezone.utc)
    tmpdir = os.path.join(root, "tmp")
    ext = "webp" if p["format"] == "webp" else "mp4"
    tmp_mp4 = os.path.join(tmpdir, f"render-{jid}.{ext}")
    listf, assf = os.path.join(tmpdir, f"render-{jid}.txt"), os.path.join(tmpdir, f"render-{jid}.ass")
    try:
        frames = select_frames(c, s, e, root)
        if not frames:
            raise RuntimeError("no frames in range")
        set_job(c, jid, status="running", started_utc=db.utcnow(), progress=0, error=None)
        files = [f for f, _ in frames]
        w0, h0 = frames[0][1]["width"] or 1280, frames[0][1]["height"] or 720
        tz = cfg.get("timezone", "America/Denver")
        stamps = [datetime.strptime(r["ts_utc"], TS).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S") for _, r in frames]
        webp = p["format"] == "webp"
        if webp and not p["scale"]:  # animated WebP is for sharing: cap the width at 960 (never upscale)
            pw, ph = (h0, w0) if p["rotate"] in (90, 270) else (w0, h0)
            if p["crop"]: pw, ph = (p["crop"][1], p["crop"][0]) if p["rotate"] in (90, 270) else (p["crop"][0], p["crop"][1])
            k = min(1.0, 960 / pw); p = {**p, "scale": [max(16, int(pw * k)), max(16, int(ph * k))]}
        vf, w, h = filter_chain(p, w0, h0, assf if p["overlay"] else None)
        open(listf, "w").write(concat_text(files, p["fps"]))
        if p["overlay"]:
            open(assf, "w").write(ass_text(stamps, p["fps"], w, h))
        n = len(files)
        codec = (["-c:v", "libwebp_anim", "-quality", "70", "-loop", "0"] if webp else
                 ["-c:v", "libx264", "-preset", p["preset"], "-crf", str(p["crf"]), "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
        # -frames:v n: the concat demuxer + -r can emit one frame too many; the count is exactly the frames selected
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listf,
               "-vf", vf, "-r", str(p["fps"]), "-frames:v", str(n), *codec, "-progress", "pipe:1", tmp_mp4]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        set_job(c, jid, pid=proc.pid)
        for line in proc.stdout:
            if line.startswith("frame="):
                set_job(c, jid, progress=min(0.99, int(line.split("=")[1]) / n))
                if c.execute("SELECT status FROM render_jobs WHERE id=?", (jid,)).fetchone()[0] == "cancelled":
                    proc.send_signal(signal.SIGTERM)
        err = proc.stderr.read()
        rc = proc.wait()
        if c.execute("SELECT status FROM render_jobs WHERE id=?", (jid,)).fetchone()[0] == "cancelled":
            raise InterruptedError("cancelled")
        if rc != 0:
            raise RuntimeError("ffmpeg failed: " + err[-300:])
        info = probe(tmp_mp4)
        want = n / p["fps"]
        if webp:
            if info.get("codec_name") != "webp" or os.path.getsize(tmp_mp4) < 100:
                raise RuntimeError(f"ffprobe check failed: {info}")
        elif info.get("codec_name") != "h264" or info.get("pix_fmt") != "yuv420p" or int(info.get("nb_frames") or n) != n or abs(info["duration"] - want) > max(1.0, want * 0.05):
            raise RuntimeError(f"ffprobe check failed: {info}")
        local0 = s.astimezone(ZoneInfo(tz))
        name = f"{job['kind']}-{local0:%Y%m%d-%H%M}-{jid}.{ext}"
        sub = job["kind"] if job["kind"] in ("daily", "weekly", "monthly") else "custom"
        final = paths.safe_path(os.path.join(root, "videos", sub, name), root)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        os.replace(tmp_mp4, final)  # atomic, same filesystem
        cur = c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,render_params_json,created_utc,duration) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (final, "video", fmt(s), tz, info.get("width"), info.get("height"), os.path.getsize(final), json.dumps(p), db.utcnow(), info.get("duration")))
        thumb = os.path.join(root, "thumbnails", f"m{cur.lastrowid}.jpg")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", files[0], "-frames:v", "1", "-vf", "scale=320:-2", thumb], timeout=60)
        set_job(c, jid, status="done", progress=1.0, output_media_id=cur.lastrowid, completed_utc=db.utcnow(), pid=None)
        log.info("render %s done: %s (%d frames)", jid, final, n)
    except InterruptedError:
        set_job(c, jid, error="cancelled", pid=None, completed_utc=db.utcnow())
    except Exception as ex:
        log.error("render %s failed: %s", jid, ex)
        set_job(c, jid, status="failed", error=str(ex)[:500], pid=None, completed_utc=db.utcnow())
    finally:
        for f in (tmp_mp4, listf, assf):
            if os.path.exists(f):
                os.unlink(f)


def worker_loop(cfg):
    c = db.connect(cfg["storage"]["db"])
    c.execute("UPDATE render_jobs SET status='failed',error='worker restarted',pid=NULL WHERE status='running'")
    c.commit()
    while True:
        r = c.execute("SELECT id FROM render_jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not r:
            time.sleep(2)
            continue
        lk = locks.acquire("render.lock", wait=30)
        if lk:
            run_job(c, r["id"], cfg)
            lk.close()


def enqueue_range(kind, cfg):
    tz = cfg.get("timezone", "America/Denver")
    today = datetime.now(ZoneInfo(tz)).date()
    if kind == "daily":
        d0 = d1 = today - timedelta(days=1)
    elif kind == "weekly":  # previous Monday..Sunday
        d1 = today - timedelta(days=today.weekday() + 1); d0 = d1 - timedelta(days=6)
    elif kind == "monthly":
        d1 = today.replace(day=1) - timedelta(days=1); d0 = d1.replace(day=1)
    else:
        raise ValueError(kind)
    s, _ = day_range(d0, tz)
    _, e = day_range(d1, tz)
    c = db.connect(cfg["storage"]["db"])
    return create_job(c, kind, s, e, {"fps": cfg["render"]["fps"], "crf": cfg["render"]["crf"], "preset": cfg["render"]["preset"]})
