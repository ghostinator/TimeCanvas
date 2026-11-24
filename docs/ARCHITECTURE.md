# Architecture
**Only ustreamer opens the camera.** `timecanvas-ustreamer` (user `timecanvas`, `DevicePolicy=closed` + video4linux only) serves MJPEG passthrough (`--encoder=HW`) on `127.0.0.1:8080`; the mode defaults to 1920x1080@30 and is overridden by `/etc/timecanvas/camera-mode.env` (written by the helper from the Camera page). Everything else reads frames over HTTP; all other units have `PrivateDevices=yes`.
**Placeholder frames.** When the camera is gone ustreamer still answers `/snapshot` with HTTP 200 and a placeholder JPEG (`X-UStreamer-Online: false`). Capture therefore requires `Online: true`, a nonzero grab timestamp, a fresh frame, the configured dimensions and a structurally valid JPEG.

| Unit | Role |
|---|---|
| camera-init.service | applies V4L2 controls: power_line_frequency=2, then saved values from `camera-controls.json` (auto modes first) |
| ustreamer.service | camera broker, restarts with backoff |
| capture.timer/.service | 5 s tick; the slot logic captures once per `interval` slot (one catch-up after downtime) |
| health.timer/.service | writes streamer/disk status into the DB every 15 s |
| render-worker.service | processes queued jobs under `render.lock` |
| render-daily.timer/.service | 00:15 America/Denver: enqueue the previous local day |
| render-weekly.timer/.service | Monday 00:30: enqueue the previous week |
| render-monthly.timer/.service | the 1st at 00:45: enqueue the previous month |
| archive.timer/.service | 02:30 upload of finished days (stored zips) and videos to OneDrive with rclone, size-verified, upload-only; takes `archive.lock` |
| cleanup.timer | 03:30 retention; takes `capture.lock`, `archive.lock`, then `render.lock`; skips unarchived days while the archive hold is on |
| alerts.timer/.service | every minute (own unit): evaluates camera-offline / no-photos / disk / archive / services / certificate, runs the alert state machine (two sightings to open, reminders, recovery), delivers to Teams and email, optional heartbeat ping |
| tailscale-cert.timer/.service | 03:30 (+random delay) fetches/renews the Let's Encrypt cert for the node's MagicDNS name, reloads nginx only on change, rolls back a cert nginx rejects |
| backup.timer | 04:00 config + DB backup (root) |
| web.service | FastAPI on 127.0.0.1:8000 |
| helper.socket / helper@.service | the only root path: fixed allowlist (restart-camera, camera-info, camera-set, camera-mode, camera-reset, apply-saved, journal, diag, archive-run) |
| nginx | 443 TLS + Basic Auth; proxies `/` and exactly `/live/stream`; streaming locations for media, zips and bulk actions; cert from Tailscale (self-signed fallback kept) |

**Locks** (`/run/timecanvas`): `capture.lock` (capture/cleanup), `render.lock` (render/cleanup), `archive.lock` (archive/cleanup). **Time**: UTC in the DB, America/Denver for display/grouping/filenames (`2026-11-19T09-01-30-0700.jpg`). Render ranges use local-midnight bounds converted to UTC, so 23/25-hour DST days work; render order comes from UTC timestamps, never filename order (see the DST note in OPERATIONS).
**Layout:** `/opt/timecanvas/{app,venv,scripts,migrations,VERSION}` (root-owned), `/etc/timecanvas`, `/var/lib/timecanvas/timecanvas.db`, `/srv/timecanvas/{images,videos,thumbnails,exports,spool,tmp,lost-and-found}` (media disk, ext4 by UUID).
**Schema:** `001_init.sql` (settings, camera_capabilities, camera_profiles, capture_events, media_files, sessions, render_jobs, health_events, pinned_media, audit_events), `002_video_duration.sql` (`media_files.duration`), `003_archive.sql` (`archive_items`: what is verified on OneDrive; key `day:YYYY-MM-DD` / `video:<id>`), `004_alerts.sql` (`alert_state`, `alert_log`). Migrations are forward-only and applied at start. The filesystem is authoritative; `python3 -m timecanvas reconcile` re-indexes.

**Dashboard code.** `app/timecanvas/web/app.py` (routes), `templates/` (Jinja2; `base.html` renders the nav and the Library/Settings tab bars from the request path), `static/` (`tc.css` tokens + layout, `htmx.min.js` vendored, `library.js` selection/shortcuts, `lightbox.js` viewer, `play.js` range player, `camera.js`, `fonts/` Atkinson Hyperlegible Next, OFL). The CSP is `script-src 'self'`: no inline handlers or scripts anywhere (a test asserts it). Media is only served by DB id.
**Render pipeline.** Frames are selected by UTC range, written to an explicit ffconcat list, filtered (crop/rotate/scale+pad/range fix, optional ASS timestamp overlay), encoded with `-frames:v <n>` so the output has exactly the selected frames, verified with ffprobe (h264/yuv420p/frame count/duration; animated WebP checks codec and size), then moved atomically. The thumbnail is the first source frame.
**Archive flow.** For each finished local day without a verified upload: build `archive-YYYY-MM-DD.zip` (stored, with `manifest.json`) in `/srv/timecanvas/tmp`, `rclone copyto`, then `rclone lsjson` size check, then record in `archive_items`; videos are uploaded as files. The first failure stops the run and is shown on the Archive page. Nothing is ever deleted by the archive.
**Capture strip.** `hour_strip()` buckets a day's frames by local hour against `3600 / interval`; cells link to `tfrom`/`tto` filters.
**Alert engine.** `alerts.evaluate()` returns the active conditions; `alerts.run()` keeps one `alert_state` row per rule (`streak` counts consecutive sightings, `status` open/ok, `last_notified_utc` drives reminders) and writes every delivery attempt to `alert_log`. Capture is only 'expected' when capture is enabled and the active session's days/hours allow it, and also were allowed one stale-window ago, so the start of a scheduled window is not a false alarm. 'No new photos' is suppressed while the streamer reports the camera offline (that alert owns it). Secrets are read from `/var/lib/timecanvas/alerts.json`.

## System inventory
Facts as of v0.3.0 (2026-11-22). This section owns them; other documents link here.

| Item | Value |
|---|---|
| Proxmox node | `pve-pueblo`, Proxmox VE 9.2.18, kernel 7.0.14-16-pve, tailnet <host-tailnet-ip> |
| VM | VMID 102 `timecanvas`, q35/SeaBIOS, 2 vCPU (`host`), 2 GiB RAM, bridge `vmbr0`, no VLAN, autostart on (`onboot: 1`, `startup: down=120`) |
| Disks | 24 GiB OS (`scsi0`) and 256 GiB media (`scsi1`, `backup=0`), both on `local-lvm` (thin, over-provisioned) |
| USB passthrough | `usb0: host=05a3:9422` (by ID, USB 2) |
| Camera | Sonix H.264 USB Camera `05a3:9422` (UVC); capture node `/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0` |
| Cabling | an active 32 ft USB repeater (see CAMERA_CAPABILITIES for why passive extensions plus a hub failed) |
| Guest OS | Debian 13 (trixie), kernel 6.12.117+deb13-amd64 |
| Network | LAN DHCP address (not needed for normal use) and the tailnet name `timecanvas.<tailnet>.ts.net` |
| Packages | nginx 1.26.3, python3 3.13.5, ffmpeg 7.1.5, ustreamer 5.4, sqlite3 3.46.1, rsync 3.5.0, jq 1.7.1, nftables 1.1.3, usbutils 018, v4l-utils 1.30.1, apache2-utils 2.4.71, openssl 3.5.7, tailscale 1.104.7, rclone 1.76.0 (official release, checksum-pinned) |
| Python venv | fastapi 0.165.0, starlette 1.10.0, uvicorn 0.54.0, Jinja2 3.1.6, python-multipart 0.0.34 |
| Beyond the original package list | nftables, usbutils, rclone, linux-image-amd64 (the cloud kernel has no USB or uvcvideo) |

## Known limitations
- `capture_events`, `health_events`, `alert_log` and `audit_events` grow without pruning (about 2,900 capture rows per day at a 30 s interval). `capture_events` is indexed by time; if the database ever becomes slow, add pruning first.
- The OneDrive archive and alerts use the organisation's accounts and servers; nothing inside the VM can alert you if the VM or its host is down, which is what the optional heartbeat is for.
