-- alert state machine (one row per rule) and delivery history
CREATE TABLE alert_state (key TEXT PRIMARY KEY, severity TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('open','ok')), streak INTEGER NOT NULL DEFAULT 0,
  opened_utc TEXT, detail TEXT, last_notified_utc TEXT, notifies INTEGER NOT NULL DEFAULT 0, resolved_utc TEXT);
CREATE TABLE alert_log (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, key TEXT NOT NULL, event TEXT NOT NULL, channel TEXT NOT NULL, ok INTEGER NOT NULL, error TEXT);
CREATE INDEX alert_log_ts ON alert_log(ts_utc);
