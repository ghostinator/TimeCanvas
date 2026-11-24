import fcntl, os, time

DIR = "/run/timecanvas"


def acquire(name, wait=0):
    """Exclusive flock on DIR/name. Returns the open file (keep it referenced) or None if busy after `wait` seconds."""
    os.makedirs(DIR, exist_ok=True)
    f = open(os.path.join(DIR, name), "w")
    end = time.time() + wait
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.time() >= end:
                f.close()
                return None
            time.sleep(0.5)
