import os

ROOT = "/srv/timecanvas"
ALLOWED = ("images", "videos", "thumbnails", "exports", "spool", "tmp", "lost-and-found")


def safe_path(p, root=ROOT, areas=ALLOWED):
    """Resolve p (symlinks included) and require it to be inside root/<allowed area>. Raises ValueError."""
    if not isinstance(p, str) or not p or "\0" in p or not os.path.isabs(p):
        raise ValueError("path must be a non-empty absolute string")
    real = os.path.realpath(p)
    rroot = os.path.realpath(root)
    for a in areas:
        base = os.path.join(rroot, a)
        if real == base or real.startswith(base + os.sep):
            return real
    raise ValueError("path outside approved roots")
