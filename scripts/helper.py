#!/usr/bin/python3
"""timecanvas root helper: the ONLY privileged code path. Socket-activated (one connection per process).
Reads one JSON line {"action":..., "args":{...}}; executes only fixed, allowlisted actions with validated args."""
import json, os, re, subprocess, sys, tempfile, time, urllib.request

sys.path.insert(0, "/opt/timecanvas/app")
from timecanvas import v4l2  # noqa: E402

DEV = "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0"
MODE_ENV = "/etc/timecanvas/camera-mode.env"
CONTROLS = "/etc/timecanvas/camera-controls.json"
STREAMER = "http://127.0.0.1:8080/state"
JOURNAL_UNITS = {"ustreamer": "timecanvas-ustreamer", "capture": "timecanvas-capture", "render": "timecanvas-render-worker",
                 "web": "timecanvas-web", "health": "timecanvas-health", "cleanup": "timecanvas-cleanup", "archive": "timecanvas-archive"}
MODE_CTRLS = ("auto_exposure", "white_balance_automatic")  # applied before the values they enable


def run(cmd, timeout=20):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr)[-60000:], r.returncode


def v4l(*a):
    return run(["v4l2-ctl", "-d", DEV, *a])


def load_saved():
    try:
        with open(CONTROLS) as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if isinstance(v, int)}
    except (OSError, ValueError):
        return {}


def save_saved(d):
    fd, tmp = tempfile.mkstemp(dir="/etc/timecanvas")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.chmod(tmp, 0o640)
    import shutil
    shutil.chown(tmp, "root", "timecanvas")
    os.replace(tmp, CONTROLS)


def read_mode():
    try:
        d = dict(l.strip().split("=", 1) for l in open(MODE_ENV) if "=" in l)
        return d.get("TC_RES"), d.get("TC_FPS")
    except OSError:
        return None, None


def write_mode(res, fps):
    fd, tmp = tempfile.mkstemp(dir="/etc/timecanvas")
    with os.fdopen(fd, "w") as f:
        f.write(f"TC_RES={res}\nTC_FPS={fps}\n")
    os.chmod(tmp, 0o640)
    import shutil
    shutil.chown(tmp, "root", "timecanvas")
    os.replace(tmp, MODE_ENV)


def streamer_ok(res, fps, wait=12):
    """True once ustreamer reports online at the requested resolution and is actually delivering frames."""
    w, h = (int(x) for x in res.split("x"))
    end = time.time() + wait
    while time.time() < end:
        try:
            r = json.load(urllib.request.urlopen(STREAMER, timeout=2))["result"]["source"]
            if r["online"] and (r["resolution"]["width"], r["resolution"]["height"]) == (w, h) and r["captured_fps"] > 0:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def a_restart_camera(_):
    out, rc = run(["systemctl", "restart", "timecanvas-camera-init.service", "timecanvas-ustreamer.service"], 60)
    return out or "restarted", rc


def a_camera_info(_):
    parts = [v4l("--list-formats-ext")[0], v4l("--list-ctrls-menus")[0]]
    res, fps = read_mode()
    return "\n".join(parts) + f"\n#MODE {res or ''} {fps or ''}\n", 0


def set_one(name, value, persist=True):
    if not re.fullmatch(r"[a-z0-9_]{1,48}", name) or not isinstance(value, int) or isinstance(value, bool):
        return "bad control", 1
    c = {x["name"]: x for x in v4l2.parse_ctrls(v4l("--list-ctrls-menus")[0])}.get(name)
    if not c:
        return "unknown control", 1
    if c["inactive"] or c["readonly"]:
        return "control inactive (switch the related auto mode off first)" if c["inactive"] else "read-only control", 1
    if c["type"] == "bool" and value not in (0, 1):
        return "bad value", 1
    if c["type"] == "menu" and value not in [m[0] for m in c["menu"]]:
        return "bad menu value", 1
    if c["type"] == "int" and c["min"] is not None and not int(c["min"]) <= value <= int(c["max"]):
        return "value out of range", 1
    out, rc = v4l(f"--set-ctrl={name}={value}")
    if rc == 0 and persist:
        d = load_saved(); d[name] = value; save_saved(d)
    return out or "ok", rc


def a_camera_set(args):
    return set_one(str(args.get("name", "")), args.get("value"))


def a_apply_saved(_):
    """Re-apply persisted control values (after reboot/replug). Mode controls first; failures are reported, not fatal."""
    saved = load_saved(); bad = []
    for name in sorted(saved, key=lambda n: (n not in MODE_CTRLS, n)):
        if set_one(name, saved[name], persist=False)[1] != 0:
            bad.append(name)
    return f"applied {len(saved) - len(bad)}/{len(saved)}" + (f"; skipped {','.join(bad)}" if bad else ""), 0


def a_camera_reset(_):
    """Reset every writable control to its driver default and forget persisted values."""
    ctrls = v4l2.parse_ctrls(v4l("--list-ctrls-menus")[0])
    for c in sorted(ctrls, key=lambda c: (c["name"] not in MODE_CTRLS)):
        if c["default"] is not None and not c["readonly"]:
            v4l(f"--set-ctrl={c['name']}={c['default']}")
    for c in ctrls:  # second pass: controls that were inactive until the first pass switched modes
        if c["default"] is not None and not c["readonly"]:
            v4l(f"--set-ctrl={c['name']}={c['default']}")
    try:
        os.unlink(CONTROLS)
    except OSError:
        pass
    return "reset to defaults", 0


def a_camera_mode(args):
    """Change the stream mode. Validates against the camera's own MJPG list, restarts ustreamer, and reverts if it does not come up."""
    try:
        w, h, f = int(args["width"]), int(args["height"]), int(args["fps"])
    except (KeyError, TypeError, ValueError):
        return "bad request", 1
    modes = v4l2.parse_modes(v4l("--list-formats-ext")[0])
    if not v4l2.valid_mode(modes, w, h, f):
        return "mode not supported by the camera", 1
    old = read_mode()
    new_res = f"{w}x{h}"
    write_mode(new_res, f)
    run(["systemctl", "restart", "timecanvas-ustreamer.service"], 60)
    if streamer_ok(new_res, f):
        return f"now {new_res} @ {f} fps", 0
    if old[0] and old[1]:
        write_mode(old[0], old[1])
    else:
        try:
            os.unlink(MODE_ENV)
        except OSError:
            pass
    run(["systemctl", "restart", "timecanvas-ustreamer.service"], 60)
    return f"{new_res} @ {f} did not start delivering frames; reverted", 1


def a_journal(args):
    u = JOURNAL_UNITS.get(args.get("unit"))
    n = args.get("lines", 100)
    if not u or not isinstance(n, int) or not 1 <= n <= 300:
        return "bad request", 1
    return run(["journalctl", "-u", u, "-n", str(n), "--no-pager", "-o", "short-iso"])


def a_archive_run(_):
    return run(["systemctl", "start", "--no-block", "timecanvas-archive.service"])


def a_diag(_):
    cmds = [["lsusb"], ["lsusb", "-t"], ["v4l2-ctl", "--list-devices"], ["v4l2-ctl", "-d", DEV, "--list-formats-ext"],
            ["v4l2-ctl", "-d", DEV, "--list-ctrls-menus"], ["systemctl", "status", "timecanvas-ustreamer", "--no-pager", "-n", "0"],
            ["systemctl", "status", "timecanvas-capture.timer", "--no-pager", "-n", "0"], ["systemctl", "list-timers", "timecanvas-*", "--no-pager"],
            ["journalctl", "-u", "timecanvas-ustreamer", "-n", "100", "--no-pager"], ["journalctl", "-u", "timecanvas-capture", "-n", "100", "--no-pager"],
            ["journalctl", "-u", "timecanvas-render-worker", "-n", "100", "--no-pager"], ["df", "-hT", "/srv/timecanvas"],
            ["findmnt", "/srv/timecanvas"], ["cat", "/opt/timecanvas/VERSION"]]
    out = []
    for c in cmds:
        out.append("### " + " ".join(c) + "\n" + run(c)[0])
    return "\n".join(out), 0


ACTIONS = {"restart-camera": a_restart_camera, "camera-info": a_camera_info, "camera-set": a_camera_set, "camera-mode": a_camera_mode,
           "camera-reset": a_camera_reset, "apply-saved": a_apply_saved, "journal": a_journal, "diag": a_diag, "archive-run": a_archive_run}


def main():
    line = sys.stdin.readline(1024)
    try:
        req = json.loads(line)
        fn = ACTIONS[req["action"]]
        args = req.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError
    except Exception:
        print(json.dumps({"ok": False, "out": "bad request"}))
        return
    try:
        out, rc = fn(args)
    except Exception as e:
        out, rc = f"error: {e}", 1
    print(json.dumps({"ok": rc == 0, "out": out}))


if __name__ == "__main__":
    main()
