"""Retention. Selects deletable media (never pinned/protected/active-render), deletes only after safe_path checks, audits everything."""
import logging, os, sys
from datetime import datetime, timedelta, timezone

from . import archive, config as cfgmod, db, locks, paths

log = logging.getLogger("timecanvas.cleanup")
TS = "%Y-%m-%dT%H:%M:%S.%fZ"


def cutoff(now, days):
    return (now - timedelta(days=days)).strftime(TS)


def active_ranges(c):
    return [(a[0], a[1]) for a in c.execute("SELECT range_start_utc,range_end_utc FROM render_jobs WHERE status IN ('queued','running')")]


def in_active_render(ranges, ts_utc):
    """True if a frame timestamp falls inside a queued/running render's range (those frames must not be deleted)."""
    return any(a <= ts_utc < b for a, b in ranges)


def plan(c, cfg, now=None):
    """Return [(media_id, path, reason)] eligible for deletion. Pure selection, no side effects."""
    now = now or datetime.now(timezone.utc)
    st = cfg["storage"]
    out = []
    active = c.execute("SELECT range_start_utc,range_end_utc FROM render_jobs WHERE status IN ('queued','running')").fetchall()
    q = ("SELECT m.id,m.path,m.ts_utc FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
         "WHERE m.media_type=? AND m.status='ok' AND m.protected=0 AND p.media_id IS NULL AND m.ts_utc<? ORDER BY m.ts_utc")
    hold = archive.hold_set(c, cfg)   # None, or the days already safely archived (frames of other days wait for the archive)
    tz = cfg.get("timezone", "America/Denver")
    for r in c.execute(q, ("image", cutoff(now, st["frame_retention_days"]))):
        if any(a[0] <= r["ts_utc"] < a[1] for a in active):
            continue  # frame belongs to a queued/running render
        if hold is not None and f"day:{archive.local_day(r['ts_utc'], tz)}" not in hold:
            continue  # not archived yet
        out.append((r["id"], r["path"], f"image older than {st['frame_retention_days']}d"))
    for r in c.execute(q, ("video", cutoff(now, st["video_retention_days"]))):
        if hold is not None and f"video:{r['id']}" not in hold:
            continue
        out.append((r["id"], r["path"], f"video older than {st['video_retention_days']}d"))
    return out


def delete_one(c, root, mid, path, reason):
    try:
        real = paths.safe_path(path, root)
    except ValueError as e:
        c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", (db.utcnow(), "cleanup", "refused", f"{mid}: {e}"))
        c.commit()
        return False
    if os.path.islink(path) or not os.path.isfile(real):
        c.execute("UPDATE media_files SET status='missing' WHERE id=?", (mid,)); c.commit()
        return False
    os.unlink(real)
    c.execute("UPDATE media_files SET status='deleted' WHERE id=?", (mid,))
    c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", (db.utcnow(), "cleanup", "delete", f"{real} ({reason})"))
    c.commit()
    return True


def prune_dirs(root):
    base = os.path.join(root, "images")
    for d, _, _ in os.walk(base, topdown=False):
        if d != base and not os.listdir(d) and not os.path.islink(d):
            os.rmdir(d)


def run(cfg=None, dry=True):
    cfg = cfg or cfgmod.load()
    root = cfg["storage"]["root"]
    if not os.path.ismount(root):
        log.error("%s not mounted; refusing", root)
        return 4
    cap, ren = locks.acquire("capture.lock", wait=120), None
    if not cap:
        log.error("capture lock busy")
        return 75
    arc = locks.acquire("archive.lock", wait=900)
    if not arc:   # an archive run is zipping frames: do not delete them underneath it
        log.error("archive running; try later")
        return 75
    ren = locks.acquire("render.lock", wait=3600)
    if not ren:
        log.error("render lock busy (render in progress); try later")
        return 75
    c = db.connect(cfg["storage"]["db"])
    cfg = cfgmod.effective(cfg, c)
    todo = plan(c, cfg)
    for mid, path, why in todo:
        if dry:
            print(f"WOULD DELETE {path}  ({why})")
        else:
            delete_one(c, root, mid, path, why)
    if not dry:
        prune_dirs(root)
    print(f"{'dry-run: ' if dry else ''}{len(todo)} item(s)")
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run(dry="--apply" not in sys.argv))
