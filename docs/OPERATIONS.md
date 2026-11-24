# Operations

Day-to-day commands. Using the dashboard is covered in USER_GUIDE; what runs where is in ARCHITECTURE.

## Status and logs
| What | Command |
|---|---|
| Timers and next runs | `systemctl list-timers 'timecanvas-*'` |
| Core services | `systemctl status timecanvas-ustreamer timecanvas-capture.timer` |
| Deployed version | `cat /opt/timecanvas/VERSION` (also in the dashboard footer and on Settings > Maintenance) |
| Media disk | `df -hT /srv/timecanvas` and `findmnt /srv/timecanvas` |
| Service logs | `journalctl -u timecanvas-<name> -n 100`, where `<name>` is one of `ustreamer`, `capture`, `render-worker`, `web`, `archive`, `cleanup`, `alerts`, `tailscale-cert`; or Settings > Maintenance > Logs |
| Alerts | Settings > Alerts, `journalctl -u timecanvas-alerts -n 20` (details in ALERTS) |
| Archive | Settings > Archive, `journalctl -u timecanvas-archive -n 50` (details in ARCHIVE) |

## Manual jobs
Run as the service user from the VM:

```bash
sudo -u timecanvas env PYTHONPATH=/opt/timecanvas/app python3 -m timecanvas capture --force
```

Other subcommands of `python3 -m timecanvas`: `render-daily`, `reconcile` (re-index the disk; refuses if `/srv/timecanvas` is not mounted), `cleanup` (dry run) and `cleanup --apply`, `archive`, `alerts`. Renders are normally queued from the Renders and Play pages. The archive can also be started with `sudo systemctl start timecanvas-archive`.

## Retention and thresholds
- `cleanup` lists what retention would delete; `cleanup --apply` deletes it. Pinned media, frames inside queued or running renders, anything outside the approved roots, and (while "keep until archived" is on) anything not yet on OneDrive are never deleted.
- The disk warning level keeps capturing and raises an alert. The critical level stops capture (event `blocked_disk`) and raises a critical alert; the dashboard and cleanup keep working.
- File management in the dashboard (bulk actions, Storage, range delete) is described in USER_GUIDE; every delete is audited.

## Camera and cabling
- ustreamer retries the device itself. Capture records `failed: camera offline` until frames are fresh again, and the health check re-applies your saved camera controls when the camera comes back (Camera page > Rescan/re-init forces it). Physical unplug and replug has been exercised by the owner without needing a VM reboot.
- A flaky USB path was the cause of every long outage so far. Use short or **active** cabling (see CAMERA_CAPABILITIES); alerts tell you within minutes when the camera drops.
- Changing cameras: `qm set 102 -usb0 host=<id>` on the host, re-run the capability probe (procedure in CAMERA_CAPABILITIES), then update the ustreamer unit device/mode and the `[camera]` section of the config.

## Certificate
```bash
sudo systemctl start timecanvas-tailscale-cert
```

Renews on demand; expiry check: `sudo openssl x509 -in /etc/timecanvas/certificates/timecanvas.crt -noout -enddate`.

## Upgrades, releases and rollback
1. Deploy with `TC_HOST=<user@vm> scripts/deploy.sh <tag>`; roll back by deploying the previous tag. DEVELOPMENT describes releasing and what a redeploy restarts.
2. Guest OS updates: `apt upgrade` in the VM. A new kernel needs a reboot; every unit comes back on boot.

## Host and capacity
### Autostart after a host reboot
VM 102 is created with `onboot: 0`. Autostart was enabled on 2026-11-19 with `infra/proxmox/set-vm-autostart.sh` (`onboot: 1`, `startup: down=120`, VM 102 only).

1. On a rebuilt VM run the script on pve-pueblo with `--dry-run` and review the output.
2. Run it again without the flag.

Without autostart the VM stays off after a host restart or power cut until started by hand. Acceptance test 40 (host reboot) passed on 2026-11-22: VM 102 autostarted and capture resumed 3 min 42 s after the host `reboot` command (guests 103/104/105 and host-side state were not inspected); see `deploy-log/test-results.md`.

### Grow the media disk
1. On the host: `qm resize 102 scsi1 +100G`.
2. In the VM: `sudo resize2fs /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi1` (online; the mount is by UUID).

`local-lvm` is thin and over-provisioned, so watch pool usage with `lvs`.

### Moving hosts
The VM is tied to pve-pueblo while the camera is attached. To move: restore the VM backup on the new host, re-attach the USB device, check `lsusb` in the VM.

## Notes
- **DST:** local-time filenames carry the UTC offset so they are unique, but across the fall-back hour `ls` order differs from time order. The index and renders use UTC and are correct.
- **Not enabled:** WebRTC (`ustreamer` plus `janus` or go2rtc) and audio (the camera exposes USB audio; `ffmpeg -f alsa`). Both would be add-ons behind the same nginx.
