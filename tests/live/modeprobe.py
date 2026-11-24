#!/usr/bin/env python3
"""Measure real delivered fps / frame sizes per MJPEG mode. Run as root ON the VM with timecanvas-ustreamer STOPPED (it owns the camera).
Usage: modeprobe.py [seconds_per_mode=10]   -> prints one line per mode."""
import os, subprocess, sys, tempfile, time

DEV = "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0"
SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
MODES = [(1920, 1080, 30), (1920, 1080, 25), (1920, 1080, 15), (1280, 720, 30), (1280, 720, 25), (1280, 720, 15)]


def urb_errors():
    return subprocess.run("dmesg | grep -ciE 'Failed to resubmit|error -71|reset high-speed'", shell=True, capture_output=True, text=True).stdout.strip()


for w, h, f in MODES:
    out = tempfile.mktemp(suffix=".mjpg")
    subprocess.run(["v4l2-ctl", "-d", DEV, f"--set-fmt-video=width={w},height={h},pixelformat=MJPG", f"--set-parm={f}"], capture_output=True)
    e0 = urb_errors(); t = time.time()
    try:
        subprocess.run(["timeout", str(SECS + 8), "v4l2-ctl", "-d", DEV, "--stream-mmap=4", "--stream-skip=5", f"--stream-count={f * SECS}", f"--stream-to={out}"], capture_output=True)
    except Exception:
        pass
    el = time.time() - t
    pk = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size", "-of", "csv=p=0", "-f", "mjpeg", out],
                        capture_output=True, text=True).stdout.split()
    sizes = [int(x) for x in pk if x.isdigit()]
    n = len(sizes)
    print(f"{w}x{h}@{f}: frames={n}/{f * SECS} wall={el:.1f}s eff_fps={n / max(el - 1, 1):.1f} avgKB={sum(sizes) / max(n, 1) / 1024:.0f} maxKB={max(sizes, default=0) / 1024:.0f} usb_errs_added={int(urb_errors()) - int(e0)}", flush=True)
    if os.path.exists(out):
        os.unlink(out)
    time.sleep(2)
