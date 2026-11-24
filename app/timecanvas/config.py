import os, tomllib

PATH = os.environ.get("TIMECANVAS_CONFIG", "/etc/timecanvas/config.toml")


def load(path=None):
    with open(path or PATH, "rb") as f:
        return tomllib.load(f)


# settings-table keys that override config.toml values: key -> (section, name, cast)
OVERRIDES = {
    "capture_interval_seconds": ("capture", "interval_seconds", int),
    "frame_retention_days": ("storage", "frame_retention_days", int),
    "video_retention_days": ("storage", "video_retention_days", int),
    "disk_warning_percent": ("storage", "disk_warning_percent", int),
    "disk_critical_percent": ("storage", "disk_critical_percent", int),
    "render_fps": ("render", "fps", int),
    "render_crf": ("render", "crf", int),
    "render_preset": ("render", "preset", str),
}


def effective(cfg, c):
    """config.toml overlaid with values saved from the Settings page."""
    import copy
    out = copy.deepcopy(cfg)
    for k, (sec, name, cast) in OVERRIDES.items():
        r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        if r:
            out[sec][name] = cast(r[0])
    r = c.execute("SELECT value FROM settings WHERE key='timezone'").fetchone()
    if r:
        out["timezone"] = r[0]
    return out
