"""The filesystem decides what exists: index unindexed files, mark missing ones, restore reappeared ones."""
import hashlib, os, sys
from datetime import datetime, timezone

from . import config as cfgmod, db, jpeg, paths


def parse_name(name, tz):
    try:
        return datetime.strptime(name.rsplit(".", 1)[0], "%Y-%m-%dT%H-%M-%S%z").astimezone(timezone.utc)
    except ValueError:
        return None


def run(cfg=None):
    cfg = cfg or cfgmod.load()
    root = cfg["storage"]["root"]
    if not os.path.ismount(root):
        print("root not mounted; refusing to reconcile (would mark everything missing)")
        return 4
    tz = cfg.get("timezone", "America/Denver")
    c = db.connect(cfg["storage"]["db"])
    added = missing = restored = 0
    known = {r["path"]: r for r in c.execute("SELECT id,path,status FROM media_files")}
    for area, typ, ext in (("images", "image", ".jpg"), ("videos", "video", ".mp4")):
        for d, _, fs in os.walk(os.path.join(root, area)):
            for f in fs:
                p = os.path.join(d, f)
                if not f.endswith(ext) or os.path.islink(p):
                    continue
                try:
                    real = paths.safe_path(p, root)
                except ValueError:
                    continue
                if real in known:
                    continue
                ts = parse_name(f, tz) or datetime.fromtimestamp(os.path.getmtime(real), timezone.utc)
                w = h = None
                if typ == "image":
                    data = open(real, "rb").read()
                    try:
                        w, h = jpeg.inspect(data)
                    except ValueError:
                        continue
                    sha = hashlib.sha256(data).hexdigest()
                else:
                    sha = None
                c.execute("INSERT INTO media_files(path,media_type,ts_utc,tz,width,height,size_bytes,sha256,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                          (real, typ, ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), tz, w, h, os.path.getsize(real), sha, db.utcnow()))
                added += 1
    for p, r in known.items():
        exists = os.path.isfile(p)
        if r["status"] == "ok" and not exists:
            c.execute("UPDATE media_files SET status='missing' WHERE id=?", (r["id"],)); missing += 1
        elif r["status"] == "missing" and exists:
            c.execute("UPDATE media_files SET status='ok' WHERE id=?", (r["id"],)); restored += 1
    c.commit()
    msg = f"reconcile: added={added} missing={missing} restored={restored}"
    c.execute("INSERT INTO audit_events(ts_utc,actor,action,detail) VALUES(?,?,?,?)", (db.utcnow(), "reconcile", "run", msg)); c.commit()
    print(msg)
    return 0


def main():
    sys.exit(run())
