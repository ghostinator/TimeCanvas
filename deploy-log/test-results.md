# Acceptance test results

## Current status
Latest known result for each acceptance test (numbers follow the original brief). A result is never stated beyond its evidence: *user-reported* means Brandon observed it, *simulated* means the camera was disabled in software (sysfs `authorized=0/1`), and **test 40 passed on 2026-11-22 with stated limits** (guests 103/104/105 and host-side state were only checked by ping, not inspected). Detail and the order things happened in are in the History below.

| # | Test | Result | Date | Evidence |
|---|---|---|---|---|
| 1 | 05a3:9422 visible in the VM | PASS | 2026-11-19 | `lsusb` in the VM |
| 2 | All of its nodes listed | PASS | 2026-11-19 | `/dev/video0-3` and the by-id links |
| 3 | Capture node documented | PASS | 2026-11-19 | docs/CAMERA_CAPABILITIES.md |
| 4 | Stable device name survives a reboot | PASS | 2026-11-19 | by-id path present after a VM reboot |
| 5 | Live feed works with a login on desktop and mobile | PASS (user-reported) | 2026-11-19 | Brandon, from his own desktop and mobile browsers |
| 6 | Requests without a login are denied | PASS | 2026-11-19 | 401 on `/`, `/media/*`, `/live/stream`, `/library`, `/static/*` |
| 7 | Feed runs 30 minutes without dropping | PASS | 2026-11-19 and 2026-11-22 | direct streamer: 178 samples, 0 offline; **through nginx with login (run by Brandon): 1800 s, 21,734 frames, avg 12.1 fps, 0 reconnects, no gap over 10 s** |
| 8 | Snapshots work while the feed is viewed | PASS | 2026-11-19 | 356/356 valid snapshots with a viewer attached |
| 9 | Manual capture produces a valid JPEG | PASS | 2026-11-19 | JPEG parsed, 1280x720 then 1920x1080 |
| 10 | Timer runs at the set interval | PASS | 2026-11-19 | events 30 s apart |
| 11 | Files sort in time order | PASS | 2026-11-22 | 303 frame names sorted equal chronological order (DST caveat in OPERATIONS) |
| 12 | Captures never overlap | PASS | 2026-11-19 | `flock` plus one attempt per slot |
| 13 | An existing file is never overwritten | PASS (by construction) | 2026-11-19 | `os.link` no-overwrite; not stress-tested |
| 14 | Database matches the files on disk | PASS | 2026-11-19 | reconcile: added 0, missing 0 |
| 15 | A malformed response is rejected | PASS | 2026-11-19 | unit tests plus the live offline run |
| 16 | A test range renders | PASS | 2026-11-19 | real jobs; the frame-count mismatch found later was fixed |
| 17 | The video plays in a browser | PASS (user-reported) | 2026-11-19 | Brandon |
| 18 | ffprobe confirms codec, size, duration, pixel format | PASS | 2026-11-19 | checked in code (h264, yuv420p, frame count, duration) and by unit test |
| 19 | The dashboard shows progress | PASS (user-reported) | 2026-11-19 | Brandon |
| 20 | A cancelled render leaves no file that looks complete | PASS | 2026-11-19 | live cancel: no temp file, no video row |
| 21 | Re-rendering leaves the source frames untouched | PASS | 2026-11-19 | unit test |
| 22 | Unplugging the camera gives a clean offline state | PASS (simulated and user-run) | 2026-11-19, 2026-11-22 | simulated via sysfs (repeated); physical unplug by Brandon, kernel log shows the re-enumerations |
| 23 | The dashboard stays up while offline | PASS (simulated) | 2026-11-19 | HTTP 200 throughout; physical run not separately observed |
| 24 | Capture fails without writing a bad file | PASS (simulated) | 2026-11-19 | frame count unchanged while offline (546 to 546) |
| 25 | Plugging back in restores feed and capture without a reboot | PASS (simulated and user-run) | 2026-11-19 | capture ok again, no reboot; saved camera controls match the device |
| 26 | The warning threshold works | PASS (unit) | 2026-11-19 | `test_thresholds`; not exercised live |
| 27 | The critical threshold stops capture | PASS (live) | 2026-11-19 | `blocked_disk` recorded, no new frames, resumed after restoring |
| 28 | The dry run lists the right files | PASS (unit) | 2026-11-19 | retention selection tests |
| 29 | Pinned files are excluded | PASS (unit) | 2026-11-19 | retention and bulk-delete tests |
| 30 | Cleanup cannot escape /srv/timecanvas | PASS (unit) | 2026-11-19 | symlink, traversal, empty-path and root cases |
| 31 | Cleanup cannot race a render | PASS (unit) | 2026-11-19 | frames in queued/running renders excluded; cleanup takes `render.lock`; not exercised live |
| 32 | No service runs as root | PASS (with listed exceptions) | 2026-11-22 | TimeCanvas services run as `timecanvas`. Root: `helper@`, `backup`, `tailscale-cert` (plus nginx master, tailscaled, sshd); see SECURITY. Earlier rows omitted `tailscale-cert` (corrected) |
| 33 | ustreamer and uvicorn ports unreachable from the LAN | PASS | 2026-11-19 | blocked from the Mac; both bound to 127.0.0.1 |
| 34 | HTTPS is on | PASS | 2026-11-19 | 443 TLS, 80 redirects; trusted Let's Encrypt certificate on the Tailscale name |
| 35 | Media and the live feed require a login | PASS | 2026-11-19 | 401 without login on the Tailscale name |
| 36 | No secrets in the repo, history, logs or docs | PASS (repo, history, docs) | 2026-11-22 | `scripts/secret-scan.sh --range --all` clean; logs are not scanned (error text is scrubbed of secrets by tests) |
| 37 | The dashboard cannot run commands or read arbitrary files | PASS (tests) | 2026-11-19 | `test_no_command_surface`; media only by database id through `safe_path` |
| 38 | No TimeCanvas key in pve-pueblo's cluster authorized_keys | PASS | 2026-11-19 | read-only check; not re-run |
| 39 | A VM reboot brings the whole stack back | PASS | 2026-11-19 | units active, mount ok, firewall persisted, captures resumed |
| 40 | A host reboot brings the VM and USB passthrough back | PASS (with limits) | 2026-11-22 | Unattended run after Brandon pre-approved a reboot of pve-pueblo. Host `reboot` issued 23:01:37 (MST); VM 102 shut down 23:01:41, booted 23:04:58 on its own (`onboot: 1`, `startup: down=120`), camera 05a3:9422 enumerated in the VM 23:05:01, ustreamer started 23:05:04, first new capture 23:05:19 (3 min 42 s after the reboot command; last frame before it 23:01:03). After: 0 failed units, all timecanvas units and nginx active, `/srv/timecanvas` mounted, dashboard answers 401 (login required) on both its Tailscale name (trusted cert) and the LAN IP, no alert opened and no alert sent. **Not verified:** host-side state (`qm list`, host journal; the host was verified before the reboot, and afterwards only by ping of its tailnet address, first seen 23:05:04, an upper bound), and guests 103/104 and LXC 105, which only answered ping on their LAN addresses (their services were not inspected). Dashboard login and the 'recovered' path were not exercised. Camera was visible on the first boot attempt; no manual `attach-usb-and-start.sh` was needed. One reboot, one run. |
| 41 | Config and DB backups work | PASS | 2026-11-19 | `scripts/backup.sh`, integrity checked |
| 42 | A restore test succeeds | PASS | 2026-11-19 | scratch restore; plus deploying v0.1.0 over the running VM from its tag and then v0.2.0 (not a from-scratch VM rebuild) |
| 43 | The working tree is clean | PASS | 2026-11-19 to 2026-11-22 | clean at every tagged deploy (v0.1.0, v0.2.0, v0.2.1, v0.3.0) |
| 44 | VERSION matches the tag | PASS | 2026-11-19 to 2026-11-22 | `/opt/timecanvas/VERSION` equals the tag at each deploy |
| 45 | The dashboard shows the same version | PASS | 2026-11-19 to 2026-11-22 | footer and Settings > Maintenance |
| 46 | Redeploying the same tag changes nothing | PASS | 2026-11-19, 2026-11-22 | v0.1.0 and v0.2.0: checksums identical, no restarts. Until 2026-11-22 a new commit with identical code restarted web and render-worker; fixed and verified 2026-11-22 |

| Extra | What | Result | Date | Evidence |
|---|---|---|---|---|
| Unit tests | full suite on the VM at every deploy | PASS | 2026-11-22 | coverage areas listed in docs/DEVELOPMENT.md; docs drift checks run everywhere |
| 1080p | 1080p@30 stable after the cabling fix | PASS | 2026-11-19 | 300/300 frames, 0 USB errors; 10-minute soak 27.6 fps average |
| Cabling | active 32 ft USB repeater instead of passive extensions plus hub | PASS (user-reported) | 2026-11-22 | Brandon: "works so much better" |
| Archive | nightly OneDrive archive, work account | PASS (user-reported) | 2026-11-22 | Brandon: "archive worked"; upload-only, size-verified |
| Alert channels | Teams, email (Postal), Uptime Kuma heartbeat | PASS (user-reported) | 2026-11-22 | each tested on its own; Teams needed a flow fix (card step on both Condition branches) |
| Alert drill | simulated outage through the real alert path | PASS | 2026-11-22 | offline 11:35:45; alert 11:40:08 and recovery 11:41:08 accepted by Teams and Postal; 10 failed captures, then normal |
| Autostart | VM 102 starts with the host | CONFIGURED, not tested | 2026-11-19 | `qm set 102 --onboot 1 --startup down=120`; other guests unchanged |

## History
The original running log, unchanged (some rows are superseded by the table above).

Legend: PASS / FAIL / NOT RUN. Simulated = sysfs `authorized=0/1` inside the VM, not a physical unplug.

| # | Test | Result | Evidence |
|---|---|---|---|
| 1 | 05a3:9422 visible in VM | PASS | lsusb in VM, 2026-11-19 |
| 2 | all nodes listed | PASS | /dev/video0-3 + by-id links |
| 3 | capture node documented | PASS | docs/CAMERA_CAPABILITIES.md |
| 9 | capture produces valid JPEG | PASS | 1280x720, ~190 KB, JPEG parsed |
| 10 | timer runs at interval | PASS | events 30 s apart |
| 13 | existing file never overwritten | PASS (by construction: os.link) | unit-level logic; not stress tested |
| 15 | malformed/placeholder response rejected | PASS | unit tests + live offline run |
| 22 | unplug -> clean offline state | PASS (simulated) | ustreamer Online:false, capture records 'failed' |
| 24 | capture fails without bad file | PASS (simulated) | file count unchanged while offline |
| 25 | replug restores without reboot | PASS (simulated) | ustreamer + capture recovered in <70 s |
| 16 | test range renders | PASS | real job on 2026-11-19 frames, 720p h264 |
| 18 | ffprobe codec/size/duration/pix_fmt | PASS | checked in code (h264, yuv420p, frame count, duration) and unit test |
| 20 | failed/cancelled job leaves no complete-looking file | PASS (failure path; cancel path NOT YET exercised live) | unit test: empty range |
| 21 | re-render leaves sources untouched | PASS | unit test: 12 sources intact |
| 28 | dry run lists right files | PASS (unit, plan selection) | tests/test_render_cleanup.py |
| 29 | pinned excluded | PASS (unit) | |
| 30 | cleanup can't escape /srv/timecanvas | PASS (unit: symlink, traversal, empty, root) | |
| U | unit tests on VM | PASS 17/17 | python3 -m unittest, 2026-11-19 |
| 6 | requests without login denied | PASS (from Mac over LAN) | https://<vm-lan-ip>/ -> 401, /live/stream -> 401 (local) |
| 33 | ustreamer/uvicorn ports unreachable from LAN | PASS | nc to :8000 and :8080 from Mac: blocked; both also bound to 127.0.0.1 |
| 34 | HTTPS on | PASS | 443 TLS, http->https 301 |
| 36 | no secrets in repo/history | PASS | history scan 2026-11-19 (only the scanner's own regex matched) |
| FW | firewall applied + persisted | PASS | nftables input default-deny; SSH/HTTPS verified from Mac after apply; rollback cancelled |
| 7 | live feed 30 min without dropping | PASS (direct streamer, loopback) | 178 state samples, 0 offline, avg 15.6 fps (min 2 once), 2026-11-19; not yet via nginx with login on desktop/mobile |
| 8 | snapshots while feed viewed | PASS | 356/356 valid snapshots with a viewer attached; viewer disconnect/reconnect at midpoint OK |
| 46 | redeploying same ref changes nothing | PASS (units); full tag check at release | two consecutive deploys of one commit: no service restarted (ActiveEnterTimestamp identical) |
| note | sporadic truncated frames | FIXED | ~1 reject per 10-20 min on the passthrough link; capture now retries up to 3x inside a tick |
| 4 | stable device name survives reboot | PASS | by-id path present after VM reboot |
| 12 | captures never overlap | PASS (lock-based; 1 pair 5-20 s apart is two adjacent slots, not concurrent) | flock + one attempt per slot |
| 14 | DB matches files | PASS | reconcile added=0 missing=0 restored=0; 90 files = 90 distinct DB paths |
| 20 | cancelled render leaves no complete-looking file | PASS (live) | job cancelled mid-run: no tmp file, no new video row, no ffmpeg left |
| 32 | no service runs as root | PASS | ustreamer, uvicorn, capture/render python run as timecanvas; only helper@ (socket-activated) and backup oneshot are root by design |
| 37 | dashboard cannot run commands/read arbitrary files | PASS (tests) | tests/test_web.py::test_no_command_surface, media only by DB id via safe_path |
| 38 | no TimeCanvas key in cluster authorized_keys | PASS | grep -ci timecanvas = 0 in /etc/pve/priv/authorized_keys (read-only check) |
| 39 | VM reboot brings whole stack back | PASS | 11 units active, mount ok, firewall persisted, captures resumed, no failed units |
| host | VMs 103/104 and LXC 105 untouched | PASS | still running, same PIDs as at preflight |
| 41/42 | config+DB backup; restore test | PASS (scratch restore, integrity ok); rebuild-from-tag still to do | scripts/backup.sh, restore.sh |
| 40 | host reboot | NOT RUN (would restart VMs 103/104 and LXC 105; needs your explicit scheduling) | |
| 5,17,19 | logged-in desktop/mobile browser checks, video playback, render progress in UI | NOT RUN (browser pane rejects the self-signed cert; needs you) | |
| 1080p | 1080p@30 stable after hub/cabling fix | PASS | modeprobe: 300/300 frames, 0 USB errors; 10-min soak: 0 offline, 117/117 snapshots, avg 27.6 fps |
| cam-ctl | camera controls via helper (live) | PASS | invalid mode/fps/name/range refused; brightness persisted and re-applied after streamer restart; 720p<->1080p mode change ~3 s; manual exposure unlocks exposure_time; reset clears saved values |
| cam-replug | saved controls re-applied after replug | NOT CONCLUSIVE | sysfs deauth/auth does not power-cycle the camera, so values survived on the device; needs the physical unplug test |
| web | 29 unit/web tests on VM | PASS | includes camera page, mode/set CSRF + validation, live page |
| cam-ui | camera page: live preview, controls, mode, Live page in a real browser | PASS (user-reported) | Brandon, 2026-11-19: "everything camera wise works" (own browser; I could not load the self-signed cert); physical-replug persistence not separately confirmed |
| files | bulk select/pin/delete/zip, storage by day, range preview==delete, sortable videos | PASS (automated) | 38 tests on VM incl. csrf, confirmation, pinned kept, symlink-escape zip, DST day stats; live smoke 200s; browser look-and-feel NOT yet checked |
| 22-25 | unplug/replug re-run | PASS (simulated) | 2026-11-19 18:2x: Online:false, dashboard 200 while offline, frames 546->546, recovery without reboot (capture ok, frames 548); physical unplug still NOT RUN |
| 27 | critical threshold stops capture (live) | PASS | thresholds lowered: `blocked_disk` recorded, frame count unchanged; restored, capture resumed |
| 35 | media and live feed require login | PASS | `/`, `/media/1/file`, `/media/1/thumb`, `/live/stream`, `/library`, `/static/tc.css` -> 401 without login |
| 11 | files sort in time order | PASS | 303 frame names sorted == chronological |
| 36 | secrets scan (history, re-run) | PASS | only the scanner's own regex line matches |
| 43-46 | rebuild/redeploy from tag v0.1.0 | PASS | deploy of the annotated tag: VERSION=v0.1.0, footer v0.1.0, second/third deploy byte-identical (checksum of /opt/timecanvas + units) and no restarts |
| web | 52 unit/web tests on VM | PASS | includes archive (fake rclone), pagination, nav, lightbox markup, no inline handlers |
| archive | OneDrive archive live | PASS (user-reported) | Brandon, 2026-11-19: "archive worked" |
| 5 (mobile) | live feed with login on mobile browsers | PASS (user-reported) | Brandon, 2026-11-19: "Mobile browsers are good" (desktop already confirmed from his own browser) |
| 17 | video plays in a browser | PASS (user-reported) | Brandon, 2026-11-19: "video playback ... good" |
| 19 | dashboard shows render progress | PASS (user-reported) | Brandon, 2026-11-19: "rendering ... good" |
| 22-25 | physical unplug/replug | PASS (user-reported, with log evidence) | Brandon unplugged and replugged the camera several times. VM kernel log shows the real disconnect/re-enumerate cycles today (e.g. 17:14:21 / 17:14:26 MST, plus earlier ones during the hub fault) and the health log records `camera offline` events; the stack recovered each time without a VM reboot. Saved controls (brightness 3, sharpness 0, 60 Hz) match the device now; the re-apply after the last replug was not separately timed |
| 40 | host reboot | NOT RUN | VM autostart enabled 2026-11-19 (`onboot: 1`, `startup: down=120`; usb0 `host=05a3:9422` unchanged; VMs 103/104 and LXC 105 settings unchanged and still running). The reboot itself restarts 103/104/105 and needs Brandon to schedule it |
| 40 | host reboot | WAIVED (not run) | 2026-11-19: Brandon asked for it to be closed out. It was **not executed**, so it is not reported as passed; autostart is configured (`onboot: 1`) but untested. Re-open by scheduling a reboot of pve-pueblo (restarts VMs 103/104 and LXC 105) |
| 40 | host reboot | PASS (with limits) | 2026-11-22: see the Current status row 40 for times and what was not verified. Supersedes the 2026-11-19 waiver; the waiver rows above are kept as history |
| 7 | live feed 30 min through nginx with login | PASS | 2026-11-19, run by Brandon from his Mac over Tailscale with a verified Let's Encrypt cert and Basic Auth (`tests/live/soak_nginx.py`): 1800 s on one connection, 21,734 frames, avg 12.1 fps, min 443 frames/minute, 0 reconnects, no gap over 10 s, HTTP 200. Frame rate is lower than the earlier direct-streamer soaks (15.6-27.6 fps) because the camera slows its rate in low evening light |
| alerts | alert delivery: Teams webhook, Postal email, Uptime Kuma heartbeat (each tested on its own) | PASS (user-reported) | Brandon, 2026-11-22: "all notifications work" |
| alerts-live | simulated camera outage through the real alert path | PASS | 2026-11-22: camera device disabled 11:35:45; "Camera offline" alert opened 11:40:08 (after the 3-minute threshold + two confirming checks) and was accepted by Teams and Postal; camera re-enabled 11:40:36; "Recovered" sent 11:41:08 to both; 10 failed captures during the outage, capture resumed, 0 open alerts afterwards. Receipt in Teams/inbox is the delivery log's "accepted" result, confirmed by Brandon separately |
| alerts-unit | 68 unit/web tests on the VM | PASS | engine (confirmation, reminders, recovery, schedule windows, escalation, retries, secrets), Postal API shape/errors, per-channel tests, validation, edit jobs/sessions |
| alerts-teams | Teams card delivery to Brandon's chat | PASS (user-reported) | Brandon, 2026-11-22: after fixing the flow's Adaptive Card expression and adding the card step to both sides of its Condition, "now we're good"; email via Postal was confirmed earlier the same day (both the alert and the recovery arrived) |
