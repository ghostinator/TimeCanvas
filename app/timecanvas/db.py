import glob, os, re, sqlite3
from datetime import datetime, timezone

MIGRATIONS = os.environ.get("TIMECANVAS_MIGRATIONS", "/opt/timecanvas/migrations")


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path):
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=10000")
    migrate(c)
    return c


def migrate(c, directory=None):
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_utc TEXT NOT NULL)")
    done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    for f in sorted(glob.glob(os.path.join(directory or MIGRATIONS, "[0-9]*.sql"))):
        v = int(re.match(r"(\d+)", os.path.basename(f)).group(1))
        if v in done:
            continue
        with open(f) as fh:
            sql = fh.read()
        c.executescript("BEGIN;" + sql + f"\nINSERT INTO schema_migrations VALUES({v},'{utcnow()}');COMMIT;")


def get_setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def health(c, level, source, message):
    c.execute("INSERT INTO health_events(ts_utc,level,source,message) VALUES(?,?,?,?)", (utcnow(), level, source, message))
    c.commit()
