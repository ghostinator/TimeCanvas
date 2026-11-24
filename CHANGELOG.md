# Changelog

## Unreleased
- **Site-specific values removed for publication:** the raw host command dump was deleted from `deploy-log/`, and the author's host, VM and workstation addresses, the VM MAC address and local paths are placeholders (`<host-tailnet-ip>`, `<vm-lan-ip>`, `<vm-mac>`, ...) in the docs and deploy records. The VM firewall allowlist (`infra/vm/nftables-timecanvas.nft`) still holds the author's own values because it is deployed as written; replace them for your network. Git history was squashed to one commit.

## v0.3.3 - 2026-11-23
- **Play preload is faster and safer:** 8 frames are requested at once (nginx already serves HTTP/2, so they share one connection), and a frame that fails to load (for example an nginx rate-limit 503) is retried up to 3 times instead of being counted as loaded. A frame takes the app about 3 ms to serve, so what limits loading speed is the network path, not the server.

## v0.3.2 - 2026-11-23
- **Play tab preloads the range:** pressing Load now fetches every frame in the background (4 at a time, nearest the playhead first) with a progress bar, and playback waits on a frame that has not arrived instead of skipping it, so there is no need to scrub through the range first. Image files are sent with `Cache-Control: private, max-age=3600` so the browser reuses what it preloaded (downloads and videos are unchanged).

Documentation and repository polish for sharing:
- **Screenshots:** real captures of the dashboard in `docs/images/` (overview, library, viewer, play, renders, camera, storage, archive, alerts, maintenance, mobile), used in the README and the user guide; the retake procedure is in DEVELOPMENT.
- **README** rewritten for GitHub (what it does, screenshots, requirements, quick start, status); `deploy-log/README.md` explains the records are one installation's history.
- **GitHub files:** `CONTRIBUTING.md`, root `SECURITY.md` (private reporting), a `tests` GitHub Actions workflow (first run passed on GitHub), `.claude/` ignored, `docs/images/*.jpg` allowed through the media ignore rules.
- **Acceptance test 40 (host reboot) now run and passed, 2026-11-22:** after a host `reboot` VM 102 autostarted, the USB camera passed through, and capture resumed 3 min 42 s later with 0 failed units and no alerts. Guests 103/104/105 and host-side state were only ping-checked. `deploy-log/test-results.md` and `docs/OPERATIONS.md` updated; the docs test no longer insists that test 40 is waived.
- `scripts/deploy.sh` no longer defaults to the author's VM: set `TC_HOST=user@vm-address`.
- Personal domains and addresses removed from tests and comments (`tests/live/soak_nginx.py` now requires `--url`).

## v0.3.1 - 2026-11-22
Fixes and a documentation overhaul found by an independent review of v0.3.0; no new features.
- **Secret scan:** `scripts/secret-scan.sh --range <revs>` (and `--range --all`) scans every commit about to be pushed; the default mode only scans staged changes.
- **Deploy:** `install.sh` restarts web and render-worker only when app code changed in content; a new commit with identical code restarts nothing.
- **Alerts:** the heartbeat keeps pinging when alerts are switched off.
- **archive-setup:** renaming the remote now leaves `rclone.conf` owned by `timecanvas` with mode 0600.
- **Docs:** documentation standard in DEVELOPMENT (one owner file per fact, immutable dated snapshots, UI text matches templates, verified-or-not markers) enforced by `tests/test_docs.py`; SECURITY now lists what runs as root and a secrets inventory (the tailscale-cert unit runs as root); ARCHITECTURE has a system inventory; OPERATIONS restructured; INSTALL, CONFIGURATION, ALERTS, ARCHIVE and CAMERA_CAPABILITIES updated; `test-results.md` has a Current status table; dated snapshots carry banners and `deploy-log/release-v0.3.0.md` was added.

## v0.3.0 - 2026-11-22
Alerts, editing of jobs, and a Postal email channel. Verified live with a simulated camera outage (alert and recovery delivered to Teams and email).
- **Alerts** (Settings > Alerts): Teams Power Automate webhook and email when the camera goes offline, no photos arrive, the disk fills, the archive fails, a service stops or the certificate is about to expire; two-sighting confirmation, reminders, recovery messages, optional heartbeat ping; own timer (`timecanvas-alerts`); migration 004; docs/ALERTS.md.
- Alerts: separate **Test Teams / Test email / Test heartbeat** buttons (work before a channel is switched on and show the real error); a TimeCanvas User-Agent on every outbound call (Cloudflare error 1010 blocked Python's default); readable HTTP error bodies; heartbeat URLs may be `http` and on private/tailnet addresses (Uptime Kuma push monitors).
- Email via the **Postal HTTP API** (server URL + API key) as well as SMTP.
- **Edit** on render jobs (in place for queued/failed/cancelled, new job for finished ones) and on sessions.
- Test fix: a test no longer depends on the current date.

## v0.2.1 - 2026-11-19
Documentation, test records and host tooling only; the application code on the VM is unchanged from v0.2.0.
- Documentation completed: README, USER_GUIDE, and updates to ARCHITECTURE, CONFIGURATION, INSTALL, SECURITY, OPERATIONS, TROUBLESHOOTING, BACKUP_AND_RESTORE, DEVELOPMENT.
- `infra/proxmox/set-vm-autostart.sh`: start VM 102 on host boot (applied on pve-pueblo; no startup order/delay, other guests untouched).
- `tests/live/soak_nginx.py`: 30-minute live-feed soak through nginx with a login (passed).
- Acceptance record: physical replug, mobile, playback and render progress confirmed by Brandon; host reboot test waived (not run).

## v0.2.0 - 2026-11-19
- `deploy.sh` records the commit (not the annotated tag object) in VERSION.
- **OneDrive archive** (rclone 1.76.0, checksum-pinned): nightly finished-day zips + videos, size-verified, upload-only; retention can wait for it (released at the critical disk level); Settings > Archive; `scripts/archive-setup.sh`; migration 003.
- **Trusted HTTPS** via `tailscale cert` (Let's Encrypt), renewed daily, rolled back if nginx rejects it.
- **UI pass:** Atkinson Hyperlegible Next (OFL) bundled; redesigned look; hourly capture strip; Library tabs (Frames / Videos / Play) and Settings tabs (General / Camera / Storage / Archive / Maintenance); Live folded into Overview; pop-up viewer; Shift-click and keyboard selection; Storage under Settings; Renders show local times; Maintenance audit grouped; Overview shows problems of the last 24 h.

## v0.1.0 - 2026-11-19 (initial deployment)
- Repository, secret-scan hook, host preflight, VM 102 creation + USB passthrough scripts.
- Camera: ustreamer broker (MJPEG passthrough, runtime resolution/fps with auto-revert, 1080p@30), camera-init, capture (slot-based, validated, atomic, no-overwrite), SQLite schema + index, reconcile.
- Rendering (FFmpeg concat, DST-safe ranges, ffprobe verified; output has exactly the selected frames), time-of-day ranges, animated WebP, browser range player; retention/cleanup with dry run, pinning, audit.
- Dashboard (Overview, Library, Renders, Sessions, Camera, Settings, Maintenance), root helper socket; Library pagination, sort/filter; bulk select/pin/zip/delete, storage by day, range delete with preview, sortable videos (migration 002); camera page with live preview and persisted controls.
- Nginx HTTPS + Basic Auth, nftables firewall with timed rollback, Tailscale install script, systemd hardening.
- Config+DB backup/restore scripts and daily timer; acceptance results in deploy-log/.
