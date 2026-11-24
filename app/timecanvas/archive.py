"""Archive to a cloud remote (OneDrive via rclone): each finished local day becomes one stored zip, each video is uploaded as-is.
Upload + verify only: this module never deletes anything, locally or on the remote. Retention may be told to wait for it (hold_set)."""
import json, logging, os, re, shutil, subprocess, sys, zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config as cfgmod, db, locks, paths, render

log = logging.getLogger("timecanvas.archive")
RCLONE = os.environ.get("TC_RCLONE", "rclone")
CONF = os.environ.get("TC_RCLONE_CONF", "/var/lib/timecanvas/rclone.conf")
DEFAULT_REMOTE = "tcarchive:TimeCanvas"
REMOTE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_-]{0,31}):([A-Za-z0-9 _./-]{0,100})$")


def valid_remote(s):
    m = REMOTE_RE.match(s or "")
    return bool(m) and ".." not in m.group(2).split("/")


def get(c):
    return {"enabled": db.get_setting(c, "archive_enabled", "0") == "1", "remote": db.get_setting(c, "archive_remote", DEFAULT_REMOTE),
            "hold": db.get_setting(c, "archive_hold", "1") == "1"}


def put(c, key, value):
    c.execute("INSERT INTO settings(key,value,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc", (key, value, db.utcnow()))
    c.commit()


def rc(*args, timeout=3600):
    return subprocess.run([RCLONE, "--config", CONF, *args], capture_output=True, text=True, timeout=timeout)


def configured(remote):
    try:
        r = rc("listremotes", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and remote.split(":")[0] + ":" in r.stdout.split()


def local_day(ts_utc, tz):
    return datetime.strptime(ts_utc, render.TS).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).date()


def archived_keys(c):
    return {r[0] for r in c.execute("SELECT key FROM archive_items WHERE status='ok'")}


def archived_days(c):
    return {k[4:] for k in archived_keys(c) if k.startswith("day:")}


def pending_days(c, tz, today):
    """[(date, frame_count)] of finished local days that still have frames and no verified upload, oldest first."""
    first = c.execute("SELECT MIN(ts_utc) FROM media_files WHERE media_type='image' AND status='ok'").fetchone()[0]
    if not first:
        return []
    done, out, d = archived_days(c), [], local_day(first, tz)
    while d < today and len(out) < 3700:
        if d.isoformat() not in done:
            s, e = render.day_range(d, tz)
            n = c.execute("SELECT COUNT(*) FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<?", (render.fmt(s), render.fmt(e))).fetchone()[0]
            if n:
                out.append((d, n))
        d += timedelta(days=1)
    return out


def hold_set(c, cfg):
    """Keys ('day:YYYY-MM-DD', 'video:<id>') retention may delete because they are already archived, or None when retention should not wait.
    The hold is released when the disk is critical: a broken archive must never fill the disk."""
    s = get(c)
    if not (s["enabled"] and s["hold"]):
        return None
    u = shutil.disk_usage(cfg["storage"]["root"])
    if u.used / u.total * 100 >= cfg["storage"]["disk_critical_percent"]:
        log.warning("disk critical: retention no longer waits for the archive")
        return None
    return archived_keys(c)


def build_zip(c, root, d, tz, dest):
    s, e = render.day_range(d, tz)
    rows = c.execute("SELECT id,path,ts_utc,size_bytes FROM media_files WHERE media_type='image' AND status='ok' AND ts_utc>=? AND ts_utc<? ORDER BY ts_utc", (render.fmt(s), render.fmt(e))).fetchall()
    items = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
        for r in rows:
            try:
                real = paths.safe_path(r["path"], root)
            except ValueError:
                continue
            if os.path.isfile(real) and not os.path.islink(real):
                z.write(real, os.path.basename(real)); items.append({"id": r["id"], "name": os.path.basename(real), "ts_utc": r["ts_utc"], "size": r["size_bytes"]})
        z.writestr("manifest.json", json.dumps({"day": d.isoformat(), "tz": tz, "frames": len(items), "items": items}))
    return len(items)


def upload(local, remote_path):
    """Copy, then confirm the remote file exists with the same size. Raises RuntimeError otherwise."""
    r = rc("copyto", local, remote_path, "--transfers", "1", "--retries", "3", "--low-level-retries", "5", "--contimeout", "30s", "--timeout", "5m")
    if r.returncode != 0:
        raise RuntimeError("upload failed: " + (r.stderr or r.stdout)[-300:])
    r = rc("lsjson", remote_path, timeout=120)
    try:
        size = json.loads(r.stdout)[0]["Size"]
    except (ValueError, IndexError, KeyError):
        raise RuntimeError("could not verify the uploaded file")
    if r.returncode != 0 or size != os.path.getsize(local):
        raise RuntimeError(f"verification failed: remote {size} bytes, local {os.path.getsize(local)}")


def record(c, kind, key, remote_path, frames, nbytes, status, error=None):
    c.execute("INSERT OR REPLACE INTO archive_items(kind,key,remote_path,frames,bytes,status,error,archived_utc) VALUES(?,?,?,?,?,?,?,?)",
              (kind, key, remote_path, frames, nbytes, status, error, db.utcnow()))
    c.commit()


def status(c, ok, msg, **kw):
    put(c, "archive_status", json.dumps({"ts_utc": db.utcnow(), "ok": ok, "msg": msg, **kw}))


def run(cfg=None):
    cfg = cfg or cfgmod.load()
    c = db.connect(cfg["storage"]["db"]); s = get(c)
    if not s["enabled"]:
        return 0
    root = cfg["storage"]["root"]
    if not os.path.ismount(root):
        log.error("%s not mounted; refusing", root); return 4
    lock = locks.acquire("archive.lock")
    if not lock:
        log.error("archive already running"); return 75
    if not valid_remote(s["remote"]) or not configured(s["remote"]):
        status(c, False, "Archive is turned on but the OneDrive connection is not set up. Run scripts/archive-setup.sh on the VM (docs/ARCHIVE.md).")
        log.error("rclone remote %s is not configured", s["remote"]); return 0
    tz = cfgmod.effective(cfg, c)["timezone"]
    base = s["remote"].rstrip("/")
    tmp = os.path.join(root, "tmp"); os.makedirs(tmp, exist_ok=True)
    days = vids = nbytes = 0
    try:
        for d, n in pending_days(c, tz, datetime.now(ZoneInfo(tz)).date()):
            z, rp = os.path.join(tmp, f"archive-{d}.zip"), f"{base}/frames/{d:%Y}/{d:%m}/{d}.zip"
            try:
                frames = build_zip(c, root, d, tz, z)
                if frames:
                    upload(z, rp); size = os.path.getsize(z)
                else:
                    rp, size = None, 0
                record(c, "day", f"day:{d}", rp, frames, size, "ok"); days += 1; nbytes += size
            finally:
                if os.path.exists(z):
                    os.unlink(z)
        done = {r[0] for r in c.execute("SELECT key FROM archive_items WHERE kind='video' AND status='ok'")}
        for r in c.execute("SELECT id,path,size_bytes FROM media_files WHERE media_type='video' AND status='ok' ORDER BY id").fetchall():
            if f"video:{r['id']}" in done:
                continue
            real = paths.safe_path(r["path"], root)
            if not os.path.isfile(real):
                continue
            rp = f"{base}/videos/{os.path.basename(real)}"
            upload(real, rp); record(c, "video", f"video:{r['id']}", rp, None, os.path.getsize(real), "ok"); vids += 1; nbytes += os.path.getsize(real)
    except Exception as ex:   # stop at the first failure: it is almost always auth or network, and retrying 30 days of zips helps nobody
        log.error("archive failed: %s", ex)
        status(c, False, str(ex)[:300], days=days, videos=vids)
        db.health(c, "warning", "archive", str(ex)[:200])
        return 1
    status(c, True, f"Uploaded {days} day(s) and {vids} video(s)." if days or vids else "Everything is already archived.", days=days, videos=vids, bytes=nbytes)
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run())
