import json, socket

SOCK = "/run/timecanvas-helper.sock"


def call(action, **args):
    """Ask the root helper to run one allowlisted action. Returns (ok, output)."""
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(90); s.connect(SOCK)
        s.sendall((json.dumps({"action": action, "args": args}) + "\n").encode())
        buf = b""
        while chunk := s.recv(65536):
            buf += chunk
        r = json.loads(buf.decode() or "{}")
        return bool(r.get("ok")), r.get("out", "")
    except Exception as e:
        return False, f"helper unavailable: {e}"
