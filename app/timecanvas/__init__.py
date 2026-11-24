def version():
    try:
        return open("/opt/timecanvas/VERSION").read().strip()
    except OSError:
        return "dev"
