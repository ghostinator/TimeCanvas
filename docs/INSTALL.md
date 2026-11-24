# Install (from scratch)
Prerequisites: Proxmox VE host reachable over SSH (see ACCESS), the Mac public key to give the VM admin, VMID 102 free.

1. **Host preflight** (read-only): see deploy-log/preflight-*.md for the commands. Confirm one `05a3:9422`, VMID free, `local-lvm` space, bridge `vmbr0`.
2. **Create VM**: copy `infra/proxmox/create-vm.sh`, `infra/proxmox/user-data.tmpl.yaml` (as `/root/timecanvas-user-data.tmpl.yaml`) and the admin public key (`/root/timecanvas-admin.pub`) to the host; run `sh create-vm.sh --dry-run`, review, then run it. It downloads and checksum-verifies the Debian 13 **generic** cloud image (the *genericcloud* kernel lacks USB/uvcvideo).
3. **Cabling**: connect the camera with short cabling or an **active USB repeater**. Passive extensions plus a hub caused USB errors and long outages (see CAMERA_CAPABILITIES).
4. **USB passthrough + start**: `infra/proxmox/attach-usb-and-start.sh` (`qm set 102 -usb0 host=05a3:9422`; USB2 only).
5. **Autostart on host boot**: on pve-pueblo run `sh infra/proxmox/set-vm-autostart.sh --dry-run`, review, then run it without the flag (VM 102 only).
6. **Baseline** in the VM: `scripts/baseline.sh` (packages, `timecanvas` user, directories). On a VM built from the older genericcloud image: install `linux-image-amd64` and remove the cloud kernel.
7. **Deploy**: `TC_HOST=<user@vm> scripts/deploy.sh <tag>` from your workstation (installs code, units, nginx, venv).
8. **Login**: on the VM `sudo htpasswd -B /etc/timecanvas/nginx/htpasswd <user>` (type the password interactively).
9. **Firewall**: `sudo sh /opt/timecanvas/scripts/firewall-apply.sh`, verify SSH/HTTPS from a second terminal, then `... keep` within 180 s.
10. **Tailscale**: `scripts/install-tailscale.sh`, then the owner runs `sudo tailscale up`. In the tailnet admin console enable *HTTPS Certificates* (DNS page; the hostname becomes public in Certificate Transparency logs). Verified 2026-11-19.
11. **Trusted certificate**: `sudo systemctl start timecanvas-tailscale-cert` (the timer then renews it daily). Open the dashboard by its `.ts.net` name.
12. **OneDrive archive** (optional): `sudo sh /opt/timecanvas/scripts/archive-setup.sh` (installs the pinned rclone, you sign in), then enable it on Settings > Archive. See ARCHIVE.
13. **Alerts** (recommended): on Settings > Alerts add the Teams webhook and/or email, press the **Test** buttons, and optionally add a heartbeat URL. See ALERTS.
14. Open the dashboard; run the acceptance list in deploy-log/test-results.md.

The UI font (Atkinson Hyperlegible Next, OFL) and htmx are bundled in the repo; nothing is loaded from a CDN.
