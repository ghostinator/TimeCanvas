CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_utc TEXT NOT NULL);
CREATE TABLE camera_capabilities (id INTEGER PRIMARY KEY, device TEXT NOT NULL, captured_utc TEXT NOT NULL, info_json TEXT NOT NULL);
CREATE TABLE camera_profiles (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, controls_json TEXT NOT NULL, created_utc TEXT NOT NULL);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, name TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT,
  interval_seconds INTEGER, schedule_json TEXT, created_utc TEXT NOT NULL);
CREATE TABLE media_files (id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,             -- canonical, absolute, inside /srv/timecanvas
  media_type TEXT NOT NULL CHECK (media_type IN ('image','video','thumbnail')),
  ts_utc TEXT NOT NULL, tz TEXT NOT NULL,
  width INTEGER, height INTEGER, size_bytes INTEGER NOT NULL, sha256 TEXT,
  session_id INTEGER REFERENCES sessions(id), render_params_json TEXT,
  created_utc TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','missing','deleted')),
  error TEXT, protected INTEGER NOT NULL DEFAULT 0);
CREATE INDEX media_type_ts ON media_files(media_type, ts_utc);
CREATE TABLE capture_events (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, status TEXT NOT NULL,
  detail TEXT, media_id INTEGER REFERENCES media_files(id), duration_ms INTEGER);
CREATE INDEX capture_events_ts ON capture_events(ts_utc);
CREATE TABLE render_jobs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, range_start_utc TEXT NOT NULL, range_end_utc TEXT NOT NULL,
  params_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','cancelled')),
  progress REAL NOT NULL DEFAULT 0, error TEXT, output_media_id INTEGER REFERENCES media_files(id),
  idempotency_key TEXT UNIQUE, pid INTEGER, created_utc TEXT NOT NULL, started_utc TEXT, completed_utc TEXT);
CREATE TABLE health_events (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, level TEXT NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX health_ts ON health_events(ts_utc);
CREATE TABLE pinned_media (media_id INTEGER PRIMARY KEY REFERENCES media_files(id), pinned_utc TEXT NOT NULL, note TEXT);
CREATE TABLE audit_events (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT);
