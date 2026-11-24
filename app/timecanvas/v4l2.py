"""Parsers for `v4l2-ctl` output (shared by the dashboard and the root helper) and mode validation."""
import re


def parse_modes(text, fmt="MJPG"):
    """{(w,h): sorted fps list, high->low} for one pixel format."""
    modes, in_fmt, size = {}, False, None
    for line in text.splitlines():
        m = re.match(r"\s*\[\d+\]:\s*'(\w+)'", line)
        if m:
            in_fmt = m.group(1) == fmt
            continue
        if not in_fmt:
            continue
        m = re.match(r"\s*Size:\s*Discrete\s+(\d+)x(\d+)", line)
        if m:
            size = (int(m.group(1)), int(m.group(2)))
            modes.setdefault(size, set())
            continue
        m = re.search(r"\(([\d.]+)\s*fps\)", line)
        if m and size:
            modes[size].add(int(round(float(m.group(1)))))
    return {k: sorted(v, reverse=True) for k, v in modes.items()}


def mode_list(modes):
    """Flat, largest-first list of (w,h,fps)."""
    return [(w, h, f) for (w, h) in sorted(modes, key=lambda s: -s[0] * s[1]) for f in modes[(w, h)]]


def valid_mode(modes, w, h, f):
    return (w, h) in modes and f in modes[(w, h)]


CTRL_RE = re.compile(r"^\s*(\w+)\s+0x\w+\s+\((int|bool|menu)\)\s*:\s*(.*)$")


def parse_ctrls(text):
    out, cur = [], None
    for line in text.splitlines():
        m = CTRL_RE.match(line)
        if m:
            d = dict(re.findall(r"(\w+)=(-?\d+)", m.group(3)))
            cur = {"name": m.group(1), "type": m.group(2), "min": d.get("min"), "max": d.get("max"), "step": d.get("step"),
                   "default": d.get("default"), "value": d.get("value"), "menu": [],
                   "inactive": "flags=inactive" in m.group(3), "readonly": "flags=read-only" in m.group(3)}
            out.append(cur)
            continue
        m = re.match(r"^\t+(-?\d+):\s*(.+)$", line)
        if m and cur is not None and cur["type"] == "menu":
            cur["menu"].append((int(m.group(1)), m.group(2).strip()))
    return out
