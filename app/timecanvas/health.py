"""Health tick: record streamer/disk/capture status into settings('status') so the dashboard reads stored records."""
import json, shutil, sys, urllib.request
from datetime import datetime, timezone

from . import config as cfgmod, db, helperclient


def run(cfg=None):
    cfg = cfg or cfgmod.load()
    c = db.connect(cfg["storage"]["db"])
    st = {"ts_utc": db.utcnow()}
    try:
        with urllib.request.urlopen(cfg["camera"]["streamer_url"] + "/state", timeout=3) as r:
            res = json.load(r)["result"]
        st["camera_online"] = bool(res["source"]["online"])
        st["fps"] = res["source"]["captured_fps"]
        st["clients"] = res["stream"]["clients"]
    except Exception as e:
        st["camera_online"] = False
        st["streamer_error"] = str(e)[:100]
    u = shutil.disk_usage(cfg["storage"]["root"])
    st["disk_pct"] = round(100.0 * (u.total - u.free) / u.total, 1)
    st["disk_free_bytes"] = u.free
    prev = db.get_setting(c, "status")
    prev_online = json.loads(prev).get("camera_online") if prev else None
    if prev_online is not None and prev_online != st["camera_online"]:
        db.health(c, "info" if st["camera_online"] else "error", "camera", "camera online" if st["camera_online"] else "camera offline")
        if st["camera_online"]:  # replugged: controls reset to defaults on the device, so re-apply the saved ones
            ok, out = helperclient.call("apply-saved")
            db.health(c, "info" if ok else "warning", "camera", f"saved controls re-applied: {out[:100]}")
    c.execute("INSERT INTO settings(key,value,updated_utc) VALUES('status',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc",
              (json.dumps(st), db.utcnow()))
    c.commit()
    return 0
