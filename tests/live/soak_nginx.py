#!/usr/bin/env python3
"""30-minute live-feed soak THROUGH nginx with a login (acceptance test 7). Run from your own machine:
    caffeinate -i python3 tests/live/soak_nginx.py --user admin --url https://<vm>.<tailnet>.ts.net/live/stream   # prompts for the password; it is never stored or printed
Reads /live/stream with HTTP Basic Auth over verified HTTPS, counts MJPEG frames, and reports drops/stalls. Stdlib only.
PASS = the single connection stayed up for the whole duration (0 reconnects) and no gap between frames exceeded --max-gap seconds."""
import argparse, base64, getpass, http.client, json, re, ssl, sys, time
from urllib.parse import urlparse


def soak(url, user, password, seconds, max_gap, verify=True):
    u = urlparse(url); end = time.time() + seconds
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    frames = reconnects = 0; gaps = []; last = None; first = None; per_min = {}; status = None; errors = []
    while time.time() < end:
        try:
            conn = (http.client.HTTPSConnection(u.hostname, u.port or 443, context=ctx, timeout=15) if u.scheme == "https"
                    else http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15))
            conn.request("GET", u.path or "/", headers={"Authorization": auth})
            r = conn.getresponse(); status = r.status
            if r.status != 200:
                errors.append(f"HTTP {r.status}"); break
            m = re.search(r"boundary=([^;\s]+)", r.getheader("Content-Type", ""))
            marker = b"--" + (m.group(1).strip('"').encode() if m else b"boundarydonotcross")
            tail = b""
            while time.time() < end:
                chunk = r.read1(65536)
                if not chunk:
                    raise ConnectionError("stream closed by server")
                buf = tail + chunk; n = buf.count(marker); tail = buf[-(len(marker) - 1):]
                if n:
                    now = time.time()
                    if last is not None and now - last > max_gap: gaps.append(round(now - last, 1))
                    last = now; first = first or now; frames += n
                    per_min[int((now - (first or now)) // 60)] = per_min.get(int((now - first) // 60), 0) + n
            conn.close()
        except Exception as ex:   # a drop: note it and reconnect, which counts against PASS
            errors.append(f"{type(ex).__name__}: {str(ex)[:80]}")
            if status not in (None, 200): break
            reconnects += 1; time.sleep(2)
    dur = (last - first) if first and last else 0
    ok = status == 200 and reconnects == 0 and not gaps and frames > 0
    return {"pass": ok, "seconds": round(dur), "frames": frames, "avg_fps": round(frames / dur, 1) if dur else 0, "reconnects": reconnects,
            "gaps_over_%ss" % max_gap: gaps, "min_frames_per_minute": min(per_min.values()) if per_min else 0, "errors": errors[:5], "http_status": status}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--url", required=True, help="e.g. https://<vm>.<tailnet>.ts.net/live/stream")
    a.add_argument("--user", required=True); a.add_argument("--minutes", type=float, default=30); a.add_argument("--max-gap", type=float, default=10)
    a.add_argument("--insecure", action="store_true", help="skip certificate verification (only for local tests)")
    a = a.parse_args()
    pw = getpass.getpass(f"Password for {a.user}: ")
    print(f"soaking {a.url} for {a.minutes:g} min ...", flush=True)
    res = soak(a.url, a.user, pw, a.minutes * 60, a.max_gap, verify=not a.insecure)
    print(json.dumps(res, indent=2)); sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
