#!/usr/bin/env python3
"""Soak test run ON the VM: a stream viewer stays connected, snapshots are taken every 5 s, the viewer disconnects at the midpoint
and reconnects; /state is sampled every 10 s. Usage: livetest.py [seconds=1800]. Prints a JSON summary."""
import json, subprocess, sys, time, urllib.request

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
B = "http://127.0.0.1:8080"
viewer = lambda: subprocess.Popen(["curl", "-s", "-o", "/dev/null", "--max-time", str(DUR), B + "/stream"])
v = viewer(); t0 = time.time(); samples = []; snaps = []; disc = False; next_state = next_snap = 0
while time.time() - t0 < DUR:
    now = time.time() - t0
    if not disc and now > DUR / 2:
        v.kill(); time.sleep(20); v = viewer(); disc = True
    if now >= next_state:
        try:
            r = json.load(urllib.request.urlopen(B + "/state", timeout=3))["result"]
            samples.append((r["source"]["online"], r["source"]["captured_fps"], r["stream"]["clients"]))
        except Exception as e:
            samples.append((False, 0, -1))
        next_state = now + 10
    if now >= next_snap:
        try:
            with urllib.request.urlopen(B + "/snapshot", timeout=5) as r:
                d = r.read(); snaps.append(r.headers.get("X-UStreamer-Online") == "true" and d[:2] == b"\xff\xd8")
        except Exception:
            snaps.append(False)
        next_snap = now + 5
    time.sleep(1)
v.kill()
fps = [s[1] for s in samples if s[0]]
print(json.dumps({"seconds": DUR, "state_samples": len(samples), "offline_samples": sum(1 for s in samples if not s[0]),
                  "min_fps": min(fps) if fps else 0, "avg_fps": round(sum(fps) / len(fps), 1) if fps else 0,
                  "snapshots": len(snaps), "snapshot_failures": snaps.count(False), "viewer_reconnected": disc,
                  "max_clients_seen": max((s[2] for s in samples), default=0)}))
