> **Snapshot as of the host preflight before v0.1.0 (2026-11-19).** A dated record that is not updated when the system changes; later corrections are appended in a dated section at the end. Current facts live in the owner files: `docs/ARCHITECTURE.md` (units, helper actions, migrations, system inventory), `docs/SECURITY.md` (what runs as root, secrets), `docs/CONFIGURATION.md` (settings), `deploy-log/test-results.md` (Current status) and `CHANGELOG.md`.

# Preflight report — pve-pueblo (read-only)

- Date: 2026-11-19 ~11:10 MST; run from `the author's Mac` as your user (macOS 27.3)
- Access: password login by Brandon in his own terminal, shared via an SSH ControlMaster socket. No keys added, no config edited.
- Identity check: `pve-pueblo` / `<host-tailnet-ip>` ✔

## Differences / flags vs. KNOWN ENVIRONMENT
1. **Camera naming:** USB ID `05a3:9422` is present (exactly one, Bus 003 Dev 011, uvcvideo, 480M behind VIA hub 2109:2822 ✔), but `/dev/v4l/by-id` names it `usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-*`, not "ARC". Serial `SN0001` is generic, so by-id may not be unique if a second identical camera is ever added. Four nodes video0-3 (matches inventory).
2. **Snippets already enabled** on `local` (`content backup,iso,snippets,vztmpl,import`) → no storage.cfg change needed for cloud-init.
3. Storage drift (minor): local 66.57% / 27.9 GiB free (was 66.53%); backups 70.49% ✔; local-lvm 39.42%, ~1036 GiB free ✔ (thin pool; 24 GiB + 256 GiB fits).
4. **Debian 13.6 netinst ISO already on `local`** (`debian-13.6.0-amd64-netinst.iso`); no cloud image present. Using a cloud image needs a download + checksum verification (approval needed).
5. **PVE firewall: `disabled/running`**, no cluster.fw. The in-VM firewall (nftables) is therefore the enforcement point for "HTTPS only from LAN/tailnet".
6. Host has sshfs mounts to other hosts. Not touched.

## Confirmations
| Check | Result |
|---|---|
| VMID 102 free | yes (only 100,101,103,104 / LXC 105,900 exist) — recheck before create |
| local-lvm active, space | active, ~1036 GiB free |
| 05a3:9422 count | 1 |
| Used by any guest config | no (grep rc=1) |
| Holding /dev/video0-3 | none (fuser empty) |
| RAM for 2 GiB VM | 92 GiB total, 45 GiB available |
| Bridge | `vmbr0` <host-lan-ip>/24, gw <gateway-ip>, on nic0 (untagged; no VLAN seen). `vmbr1` has no ports (isolated) |
| DHCP on 192.168.1.0/24 | **unverified** (router likely <gateway-ip>) — will check on first boot |
| Tailnet | host is <host-tailnet-ip>; CIDR for firewall must be confirmed by Brandon (not assumed) |
| Host | Debian 13, PVE 9.2.18, kernel 7.0.14-16-pve, DeskMini, AMD Raphael |

## USB topology
Bus 003: root hub → VIA hub (Port 2) → camera (Port 1: video ×3, audio ×2) and AICSemi 368b:8d85 (Port 2, **not touched**).
By-path: `pci-0000:03:00.4-usb-0:2.1:1.0-video-index0..3`.

## Open decisions for Brandon
1. LICENSE choice. 2. Debian cloud image download vs. existing netinst ISO. 3. Tailnet CIDR / LAN CIDR (192.168.1.0/24 observed) for firewall. 4. Tailscale in VM? 5. Hostname/IP: DHCP first, then reservation.

The raw command output was removed before publication (it listed other machines on the network).
