import sys
cmd = sys.argv.pop(1) if len(sys.argv) > 1 else ""
if cmd == "capture":
    from .capture import main; main()
elif cmd == "cleanup":
    from .cleanup import main; main()
elif cmd == "alerts":
    from .alerts import main; main()
elif cmd == "archive":
    from .archive import main; main()
elif cmd == "reconcile":
    from .reconcile import main; main()
elif cmd == "health":
    from .health import run; sys.exit(run())
elif cmd == "render-worker":
    import logging
    from . import config, render
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    render.worker_loop(config.load())
elif cmd in ("render-daily", "render-weekly", "render-monthly"):
    from . import config, render
    print("enqueued job", render.enqueue_range(cmd.split("-")[1], config.load()))
else:
    sys.exit("usage: python3 -m timecanvas capture|cleanup [--apply]|archive|alerts|reconcile|health|render-worker|render-daily|render-weekly|render-monthly")
