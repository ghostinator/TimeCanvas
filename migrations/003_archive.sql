-- what has been uploaded to the archive remote (OneDrive via rclone). key = 'day:YYYY-MM-DD' (zip of that local day's frames) or 'video:<media id>'
CREATE TABLE archive_items (id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('day','video')), key TEXT NOT NULL UNIQUE, remote_path TEXT,
  frames INTEGER, bytes INTEGER, status TEXT NOT NULL CHECK (status IN ('ok','failed')), error TEXT, archived_utc TEXT NOT NULL);
