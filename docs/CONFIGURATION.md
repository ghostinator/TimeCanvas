# Configuration
`/etc/timecanvas/config.toml` (installed once from `config/config.example.toml`, never overwritten by deploys, never in git). Values saved on the **Settings** page live in the DB `settings` table and override the file for: capture interval (10-3600 s), frame/video retention, disk warning/critical %, render fps/crf/preset, timezone, capture enabled.
Camera mode (resolution/fps) is changed on the **Camera** page. The root helper validates it against the camera's own MJPG list, writes `/etc/timecanvas/camera-mode.env` (read by the ustreamer unit) and restarts ustreamer; if the new mode does not deliver frames within 12 s it is reverted. Capture validates frames against the size ustreamer reports, so `[camera]` width/height/fps in config.toml are informational only. Camera control values (brightness, exposure, ...) set on the Camera page are saved in `/etc/timecanvas/camera-controls.json` and re-applied by `timecanvas-camera-init.sh` on every streamer start, and by the health tick when the camera comes back online. Both files are machine state (not in git, included in the config backup). The camera device path is fixed in the unit.
Defaults: interval 30 s, FRAME_RETENTION_DAYS=30, VIDEO_RETENTION_DAYS=365, warning 80 %, critical 90 % (capture stops, nothing auto-deleted; there is no emergency auto-delete policy).
Sessions (Sessions page): named window with optional interval override and days/hours schedule; the newest active session applies.

## Where each setting lives
| Setting | Where | Range / default |
|---|---|---|
| timezone | config.toml / Settings | `America/Denver` |
| capture enabled | Settings (DB `capture_enabled`) | on |
| capture interval | `[capture] interval_seconds` / Settings | 10-3600 s, default 30 |
| frame / video retention | `[storage]` / Settings | 1-3650 days, default 30 / 365 |
| disk warning / critical | `[storage]` / Settings | warning 50-98 (80), critical 51-99 (90), warning must be below critical |
| render fps / crf / preset | `[render]` / Settings | 1-60 (30) / 14-35 (23) / ffmpeg preset (medium) |
| camera resolution + fps | Camera page -> `camera-mode.env` | the camera's own MJPG list; default 1920x1080@30 |
| camera controls | Camera page -> `camera-controls.json` | per control range from V4L2 |
| archive on/off, folder, hold | Archive page (DB `archive_enabled`, `archive_remote`, `archive_hold`) | off, `tcarchive:TimeCanvas`, hold on |
| OneDrive token | `/var/lib/timecanvas/rclone.conf` (0600, `timecanvas`) | created by `scripts/archive-setup.sh` |
| login | `/etc/timecanvas/nginx/htpasswd` | typed on the VM, never in git |
| alert switches and thresholds | Alerts page (DB `alerts_enabled`, `alert_on_*`, `alert_stale_minutes` 3-1440 (10), `alert_offline_minutes` 1-1440 (3), `alert_remind_hours` 1-72 (6)) | on |
| alert channels | Alerts page (DB `alert_teams_on`, `alert_email_on`, `alert_email_method` postal/smtp, `alert_postal_url`, `alert_smtp_*`, `alert_mail_from/to`) | off until configured |
| Teams webhook, Postal API key, SMTP password, heartbeat URL | `/var/lib/timecanvas/alerts.json` (0600) | typed in the dashboard, never shown back |

Fixed in code: slot logic (5 s tick), render and capture locks, zip caps (3000 files / 3 GiB), Play cap (3000 frames), bulk selection cap (2000 ids), pagination sizes (24/60/120/240), WebP width cap (960 px). Render defaults per job are the Settings values; the Play page passes its speed as the fps.

## Settings-table keys
These are the names stored in the database `settings` table by the dashboard (they override `config.toml` where one exists).

| Page | Keys |
|---|---|
| General | `capture_enabled`, `capture_interval_seconds`, `frame_retention_days`, `video_retention_days`, `disk_warning_percent`, `disk_critical_percent`, `render_fps`, `render_crf`, `render_preset`, `timezone` |
| Archive | `archive_enabled`, `archive_remote`, `archive_hold` |
| Alerts: switches | `alerts_enabled`, `alert_on_*` (one per check: `camera_offline`, `capture_stale`, `disk`, `archive`, `service`, `cert`) |
| Alerts: thresholds | `alert_stale_minutes`, `alert_offline_minutes`, `alert_remind_hours` |
| Alerts: channels | `alert_teams_on`, `alert_email_on`, `alert_email_method`, `alert_postal_url`, `alert_smtp_*`, `alert_mail_from`, `alert_mail_to` |

Ranges and defaults are in the table above. Secrets are not settings; they are listed in SECURITY under *Secrets inventory*.
