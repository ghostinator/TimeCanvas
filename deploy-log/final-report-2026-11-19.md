> **Snapshot as of v0.2.0 (2026-11-19).** A dated record that is not updated when the system changes; later corrections are appended in a dated section at the end. Current facts live in the owner files: `docs/ARCHITECTURE.md` (units, helper actions, migrations, system inventory), `docs/SECURITY.md` (what runs as root, secrets), `docs/CONFIGURATION.md` (settings), `deploy-log/test-results.md` (Current status) and `CHANGELOG.md`.

# TimeCanvas final report (2026-11-19)

Releases: **v0.1.0** (initial deployment, commit `7720b0d`) and **v0.2.0** (UI pass, Tailscale HTTPS, OneDrive archive). Acceptance results below are only for tests that were actually run; anything not run says so.

## 1-8 Infrastructure
1. **Node:** `pve-pueblo`, Proxmox VE 9.2.18, kernel 7.0.14-16-pve (Debian 13, DeskMini, AMD Raphael). Tailnet <host-tailnet-ip>.
2. **VM:** VMID **102** `timecanvas`, LAN **<vm-lan-ip>** (DHCP; reserve MAC `<vm-mac>`), tailnet <vm-tailnet-ip> / `timecanvas.<tailnet>.ts.net`. Bridge `vmbr0`, no VLAN. 2 vCPU (`host`), 2 GiB RAM, q35/SeaBIOS, disks: 24 GiB OS (scsi0) + 256 GiB media (scsi1, `backup=0`), both on `local-lvm` (thin). Debian 13 (trixie), kernel 6.12.117+deb13-amd64. Config: `deploy-log/vm102-config-final-2026-11-19.txt`.
3. **USB passthrough:** `usb0: host=05a3:9422` (by ID, USB 2 only). VM 103/104 and LXC 105 and the AICSemi device were not touched (verified same PIDs).
4. **Camera:** `05a3:9422` Sonix H264 USB Camera (UVC; also exposes snd-usb-audio).
5. **Stable path:** `/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0` (capture node; index1-3 are metadata/H.264 nodes, see docs/CAMERA_CAPABILITIES.md).
6. **Format:** MJPEG passthrough (`ustreamer --encoder=HW`), **1920x1080 @ 30 requested**; observed 15-28 fps depending on exposure (an earlier 10-min soak averaged 27.6 fps; evening shots show ~16 fps). Modes are switchable at runtime from the Camera tab (validated, auto-revert).
7. **Controls** (Camera tab, saved in `/etc/timecanvas/camera-controls.json`, re-applied when the camera comes online): brightness, contrast, saturation, hue, white balance (auto + temperature), gamma, gain, power-line frequency (set to 60 Hz), sharpness, backlight compensation, auto exposure / exposure time, dynamic framerate. Currently saved: brightness 3, power line 60 Hz, sharpness 0, dynamic framerate on.
8. **Dashboard:** `https://<vm>.<tailnet>.ts.net/` (trusted Let's Encrypt cert from `tailscale cert`, auto-renewed daily); `https://<vm-lan-ip>/` also works with a certificate-name warning. Pages: Overview, Library (Frames/Videos/Play), Renders, Sessions, Settings (General/Camera/Storage/Archive/Maintenance).

## 9-16 Configuration
9. **Auth:** nginx HTTP Basic Auth (`/etc/timecanvas/nginx/htpasswd`). The password was typed by Brandon only; no password, hash or key is in the repo, its history, logs or docs. The app accepts only requests carrying nginx's `X-Remote-User`.
10. **Capture interval:** 30 s (Settings; per-session overrides via Sessions).
11. **Timezone:** America/Denver (DST-safe day ranges).
12. **Directories:** `/srv/timecanvas/{images,videos,thumbnails,exports,spool,tmp}` (media disk, ext4 by UUID), `/opt/timecanvas/{app,scripts,migrations,venv,VERSION}`, `/etc/timecanvas/{config.toml,certificates,nginx,camera-*}`, `/var/lib/timecanvas/{timecanvas.db,rclone.conf,cache}`, `/var/backups/timecanvas`, `/run/timecanvas` (locks).
13. **Retention/thresholds:** frames 30 days, videos 365 days; disk warning 80 %, critical 90 % (critical stops capture). Pinned/protected items and frames in queued/running renders are never deleted; cleanup waits for the OneDrive archive unless the disk is critical.
14. **Packages (VM):** nginx 1.26.3, python3 3.13.5, ffmpeg 7.1.5, ustreamer 5.4, sqlite3 3.46.1, rsync 3.5.0, jq 1.7.1, nftables 1.1.3, usbutils 018, v4l-utils 1.30.1, apache2-utils 2.4.71, openssl 3.5.7, tailscale 1.104.7, **rclone 1.76.0** (official release, checksum-pinned; Debian's 1.60 is too old for OneDrive). Python venv: fastapi 0.165.0, starlette 1.10.0, uvicorn 0.54.0, Jinja2 3.1.6, python-multipart 0.0.34. Packages beyond the original list: nftables, usbutils, rclone, linux-image-amd64 (the cloud kernel has no USB/uvcvideo).
15. **Units:** services `ustreamer`, `camera-init`, `web`, `render-worker`, socket `helper` (root, JSON action allowlist); timers `capture` (5 s tick, slot logic), `health`, `render-daily` 00:15, `render-weekly` Mon 00:30, `render-monthly` 1st 00:45, **`archive` 02:30**, `cleanup` 03:30, `tailscale-cert` 03:30, `backup` 04:00 (all America/Denver).
16. **Firewall:** nftables input default-deny; SSH/80/443 only from 192.168.1.0/24 and the Mac's tailnet address; ustreamer (:8080) and uvicorn (:8000) bind to 127.0.0.1 only.

## 17 Acceptance results
See `deploy-log/test-results.md` (running log) and the table below. **PASS** = run and passed. **Simulated** = sysfs `authorized=0/1`, not a physical unplug.

| # | Result | Notes |
|---|---|---|
| 1-4 | PASS | device, nodes, documented node, by-id survives reboot |
| 5 | PASS desktop (Brandon, own browser, signed in) and mobile browsers (Brandon-reported) | |
| 6 | PASS | `/`, `/media/*`, `/live/stream`, `/library`, `/static/*` all 401 without login |
| 7 | PASS (30 min direct streamer, **and** 30 min through nginx with login) | nginx run by Brandon: 21,734 frames, avg 12.1 fps, 0 reconnects, no gap over 10 s |
| 8 | PASS | 356/356 snapshots with a viewer attached |
| 9-15 | PASS | valid JPEG, interval, time-sorted names (303 frames verified), lock-based no-overlap, no-overwrite (os.link), reconcile 0 diffs, malformed rejected |
| 16, 18, 20, 21 | PASS | real renders (frame count fixed to exactly the selected frames), ffprobe checks, cancel leaves nothing, sources untouched |
| 17, 19 | PASS (Brandon-reported) | video playback in the browser and render progress in the UI |
| 22-25 | PASS (simulated re-run 2026-11-19 18:2x **and** physical, Brandon-reported) | simulated: offline header, dashboard 200 while offline, no frame written (546 -> 546), recovery without reboot. Physical: Brandon unplugged/replugged several times; the VM kernel log shows the real re-enumerations and the stack recovered each time without a VM reboot. Saved controls match the device now (re-apply after the last replug not separately timed) |
| 26 | PASS (unit, `test_thresholds`) | |
| 27 | PASS (live) | thresholds lowered: capture recorded `blocked_disk`, no new frames; restored, capture resumed |
| 28-30 | PASS (unit) | dry run, pinned excluded, no escape from the media root |
| 31 | PASS (unit; cleanup also takes `render.lock`) | not exercised live |
| 32 | PASS | ustreamer, uvicorn, capture/render run as `timecanvas`; root only for nginx master (workers `www-data`), the socket-activated helper and the backup oneshot, by design |
| 33-35 | PASS | ports not reachable from LAN, HTTPS on, media + live behind login |
| 36 | PASS | history scan: only the scanner's own regex line matches; no keys/tokens/hashes/tailnet name/email in tracked files |
| 37 | PASS (tests) | no command/file-browse surface; media only by DB id through `safe_path` |
| 38 | PASS (read-only check earlier) | no TimeCanvas key in the cluster `authorized_keys` |
| 39 | PASS | VM reboot: stack, mount, firewall, captures back |
| 40 | **WAIVED, not run** | Brandon closed it out on 2026-11-19 without running it (a host reboot restarts VMs 103/104 and LXC 105). It is not reported as passed. VM 102 autostart is configured but untested |
| 41, 42 | PASS | backup + scratch restore (integrity ok); **rebuild-from-tag**: v0.1.0 was deployed onto the running VM from the tag and verified, then v0.2.0 restored (not a from-scratch VM rebuild) |
| 43-46 | PASS for v0.1.0 (clean tree, VERSION=tag, footer shows tag, redeploy byte-identical + no restarts); v0.2.0 recorded in `v0.2.0-verification.md` | |
| Unit | PASS | 52 tests on the VM (paths, retention, DST, render ordering, settings, filenames, migrations, thresholds, auth, CSRF, archive with a fake rclone) |

## 18 Backup policy
Daily 04:00: SQLite `.backup` (integrity-checked) + `/etc/timecanvas` + pinned-video list into `/var/backups/timecanvas` (never on `local`/`backups` storage for frames). The rolling frame archive is excluded from Proxmox backups (`backup=0` on the media disk). **Off-VM copy:** nightly OneDrive archive (finished-day zips + videos, size-verified, upload-only). `rclone.conf` (OneDrive token) is deliberately not in any backup. See docs/BACKUP_AND_RESTORE.md, docs/ARCHIVE.md.

## 19 Limitations
- Not verified: the host reboot test (test 40, waived by Brandon, not run). The VM was created with `onboot: 0`; **autostart was enabled on 2026-11-19** (`qm set 102 --onboot 1 --startup down=120`, via `infra/proxmox/set-vm-autostart.sh`, VM 102 only; 103/104/105 verified unchanged), so a host restart should bring it back, but that has not been tested.
- 1080p stability depends on cabling; a bad powered hub caused USB -71 error loops earlier (replaced). No camera H.264 or audio capture is used.
- Thin-pool overcommit: 1.69 TiB provisioned vs the pool; watch the host's pool usage. The dashboard is reached by its Tailscale name, so the VM's DHCP address does not need a reservation.
- OneDrive archive uses your organisation's tenant policies; the archive never deletes remote data.
- Retention hold relies on the archive; a failing archive is released at the critical disk threshold.

## 20 Rollback
- Code: `scripts/deploy.sh v0.1.0` (any tag/commit; idempotent, restarts only what changed). Migrations are forward-only: v0.1.0 code ignores the later `archive_items` table and duration column.
- Config/DB: `scripts/restore.sh <backup>`; VM disks are on thin LVM (use a Proxmox snapshot before risky host work).
- Camera mode/controls: Camera tab (auto-revert on a mode that delivers no frames; "Reset all to defaults").
- Firewall mistake: `firewall-apply.sh` arms a 180 s timed rollback.

## 21 Git summary
Location `<repo>`, branch `main`, tags `v0.1.0` (7720b0d, annotated) and `v0.2.0`. Remote `origin` = private GitHub repo `ghostinator/TimeCanvas` (pushed 2026-11-19 with Brandon's approval). Conventional Commits, feature branches merged with `--no-ff`.

## 22 How Brandon connects
- **pve-pueblo:** `https://<host-tailnet-ip>:8006` (console fallback). SSH as root needs the password (typed by Brandon; the agent's keys are not accepted): `ssh root@<host-tailnet-ip>`. TimeCanvas never added a key there.
- **VM:** `ssh brandon@<vm-lan-ip>` (key `<admin>@<workstation>` via the agent; password SSH disabled), or over the tailnet `ssh brandon@timecanvas`.

## Extras
- **File manifest:** `app/timecanvas/` (capture, render, cleanup, archive, reconcile, health, config, db, paths, jpeg, locks, v4l2, helperclient, files, web/), `migrations/001-003`, `scripts/`, `systemd/`, `nginx/`, `infra/proxmox/`, `docs/`, `tests/`, `deploy-log/`.
- **Config paths:** `/etc/timecanvas/config.toml` (+ settings table overrides), `camera-mode.env`, `camera-controls.json`, `/etc/nginx/sites-available/timecanvas`, `/etc/nftables.conf`.
- **Status:** `systemctl list-timers 'timecanvas-*'`; `systemctl status timecanvas-{web,ustreamer,render-worker}`; `journalctl -u timecanvas-capture -n 50`; dashboard Overview/Maintenance; `curl -s http://127.0.0.1:8080/state` on the VM.
- **Manual capture/render:** `sudo -u timecanvas env PYTHONPATH=/opt/timecanvas/app python3 -m timecanvas capture`; renders are queued from Renders/Play (or `python3 -m timecanvas render-daily`); `sudo systemctl start timecanvas-archive`.
- **Grow the media disk:** enlarge `scsi1` in Proxmox (`qm resize 102 scsi1 +100G`), then in the VM `sudo resize2fs /dev/sdb` (the mount is by UUID, no remount needed).
- **WebRTC/audio upgrade path:** keep ustreamer as the sole camera opener; add a WebRTC gateway (e.g. go2rtc/Janus) reading its MJPEG or the camera's H.264 node, and expose audio from the UVC mic (`snd-usb-audio` is already passed through) via that gateway. The capture/render pipeline needs no change.

## Corrections (appended 2026-11-22, as of v0.3.0)
The body above is unchanged. These statements are out of date or were wrong:
- **Item 15 (units):** v0.3.0 added `timecanvas-alerts.timer` (every minute) and its service; see ARCHITECTURE.
- **Item 8 (dashboard):** Settings now has the tabs General, Camera, Storage, Archive, Alerts and Maintenance.
- **Test 32 / root:** `timecanvas-tailscale-cert.service` also runs as root (as do `helper@` and `backup`, plus the nginx master). The table row and SECURITY at the time omitted it; SECURITY now lists all of them.
- **Test counts (52 tests):** the suite has grown; DEVELOPMENT describes coverage instead of counting.
- **`migrations/001-003`:** there are now four migrations (`004_alerts.sql`).
- **Acceptance status:** test 7 through nginx with a login passed on 2026-11-22; tests 5 (mobile), 17, 19 and the physical replug (22-25) were later confirmed by Brandon; test 40 is waived and not run. The authoritative table is `deploy-log/test-results.md` (Current status).
- **Item 19 limitations:** the line about unverified physical replug, mobile, playback and the nginx soak no longer applies; the DHCP-reservation advice was dropped because the dashboard is reached by its Tailscale name.

