"""File management: bulk selection, day/range queries, safe bulk delete and zip export. Pure functions over the DB + filesystem."""
import os, tempfile, zipfile
from datetime import date, datetime, timedelta, timezone

from . import cleanup, db, paths, render

MAX_IDS = 2000
ZIP_MAX_FILES = 3000
ZIP_MAX_BYTES = 3 * 1024 ** 3


def range_rows(c, start_utc, end_utc, types=("image",), include_pinned=True):
    """Media rows (sqlite Rows incl. pinned flag) whose timestamp is in [start,end)."""
    q = ("SELECT m.*, (p.media_id IS NOT NULL) AS pinned FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
         "WHERE m.status='ok' AND m.media_type IN (%s) AND m.ts_utc>=? AND m.ts_utc<? ORDER BY m.ts_utc, m.id" % ",".join("?" * len(types)))
    rows = c.execute(q, (*types, render.fmt(start_utc), render.fmt(end_utc))).fetchall()
    return rows if include_pinned else [r for r in rows if not r["pinned"]]


def rows_by_ids(c, ids):
    ids = [int(i) for i in ids][:MAX_IDS]
    if not ids:
        return []
    return c.execute("SELECT m.*, (p.media_id IS NOT NULL) AS pinned FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
                     "WHERE m.status='ok' AND m.id IN (%s) ORDER BY m.ts_utc, m.id" % ",".join("?" * len(ids)), ids).fetchall()


def deletable(c, rows):
    """Split rows into (deletable, skipped_pinned, skipped_render). Pinned/protected and frames in queued/running renders are never deletable."""
    ranges = cleanup.active_ranges(c)
    ok, pinned, busy = [], 0, 0
    for r in rows:
        if r["pinned"] or r["protected"]:
            pinned += 1
        elif r["media_type"] == "image" and cleanup.in_active_render(ranges, r["ts_utc"]):
            busy += 1
        else:
            ok.append(r)
    return ok, pinned, busy


def bulk_delete(c, root, rows, reason):
    ok, pinned, busy = deletable(c, rows)
    deleted = sum(1 for r in ok if cleanup.delete_one(c, root, r["id"], r["path"], reason))
    return {"deleted": deleted, "failed": len(ok) - deleted, "skipped_pinned": pinned, "skipped_render": busy}


def bulk_pin(c, rows, pin=True):
    for r in rows:
        if pin:
            c.execute("INSERT OR IGNORE INTO pinned_media VALUES(?,?,NULL)", (r["id"], db.utcnow()))
        else:
            c.execute("DELETE FROM pinned_media WHERE media_id=?", (r["id"],))
    c.commit()
    return len(rows)


def build_zip(root, rows, tmpdir=None):
    """Write the selected files (stored, no recompression) to a temp zip; returns its path. ValueError if over the caps.
    Every path is re-resolved with safe_path; unreadable/escaping paths are skipped, never followed."""
    files = []
    for r in rows:
        try:
            p = paths.safe_path(r["path"], root)
        except ValueError:
            continue
        if os.path.isfile(p):
            files.append(p)
    if not files:
        raise ValueError("nothing to download")
    if len(files) > ZIP_MAX_FILES or sum(os.path.getsize(f) for f in files) > ZIP_MAX_BYTES:
        raise ValueError(f"too large for one zip (max {ZIP_MAX_FILES} files / {ZIP_MAX_BYTES // 1024 ** 3} GiB); narrow the selection")
    fd, out = tempfile.mkstemp(suffix=".zip", dir=tmpdir or os.path.join(root, "tmp"))
    os.close(fd)
    seen = set()
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for f in files:
                name = os.path.basename(f)
                if name in seen:
                    name = f"{os.path.basename(os.path.dirname(f))}-{name}"
                seen.add(name)
                z.write(f, name)
    except Exception:
        os.unlink(out)
        raise
    return out


def day_stats(c, d, tz):
    s, e = render.day_range(d, tz)
    r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(m.size_bytes),0) b, COALESCE(SUM(p.media_id IS NOT NULL),0) pinned "
                  "FROM media_files m LEFT JOIN pinned_media p ON p.media_id=m.id "
                  "WHERE m.media_type='image' AND m.status='ok' AND m.ts_utc>=? AND m.ts_utc<?", (render.fmt(s), render.fmt(e))).fetchone()
    v = c.execute("SELECT COUNT(*) FROM media_files WHERE media_type='video' AND status='ok' AND ts_utc>=? AND ts_utc<?", (render.fmt(s), render.fmt(e))).fetchone()[0]
    return {"day": d, "frames": r["n"], "bytes": r["b"], "pinned": r["pinned"], "videos": v}


def month_days(y, m):
    d = date(y, m, 1)
    while d.month == m:
        yield d
        d += timedelta(days=1)


def summarize(rows):
    return {"count": len(rows), "bytes": sum(r["size_bytes"] for r in rows)}
