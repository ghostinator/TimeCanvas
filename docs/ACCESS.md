# Access

| What | Value |
|---|---|
| Hypervisor | pve-pueblo, tailnet `<host-tailnet-ip>`, web UI https://<host-tailnet-ip>:8006 (console fallback) |
| VM | VMID 102 `timecanvas`, LAN `<vm-lan-ip>` (DHCP; not needed for normal use because the dashboard is reached by its Tailscale name; MAC `<vm-mac>`), admin user `brandon` |
| Dashboard | `https://<vm-name>.<tailnet>.ts.net/` (trusted Let's Encrypt cert, Basic Auth); `https://<vm-lan-ip>/` still works with a certificate-name warning |

**Mac -> pve-pueblo.** No `~/.ssh/config` alias exists. The Bitwarden SSH agent holds keys, but none is accepted by pve-pueblo (`Permission denied (publickey,password)`); the working route is password login typed by the owner. For automation the owner opens a shared connection (no key material changes anywhere):

    ssh -o ControlMaster=yes -o ControlPath=/tmp/tc-pve.sock -o ControlPersist=4h -o PreferredAuthentications=password,keyboard-interactive root@<host-tailnet-ip> 'hostnamectl --static'

Then `ssh -o ControlPath=/tmp/tc-pve.sock -o BatchMode=yes root@<host-tailnet-ip> <cmd>`. Always verify `hostnamectl --static` = `pve-pueblo` and `tailscale ip -4` = `<host-tailnet-ip>`.
`/root/.ssh/authorized_keys` on the host is the cluster key file; no TimeCanvas key was added to it.

**Mac -> VM.** `ssh brandon@<vm-lan-ip>` using the agent key `<admin>@<workstation>` (public key installed by cloud-init; password SSH disabled). Passwordless sudo, key-only account.

**Never** copy private keys, agent sockets, vault exports or passwords into the repo, the VM or the logs.

## Trusted HTTPS over Tailscale

`scripts/tailscale-cert.sh` asks Tailscale for the Let's Encrypt certificate of the VM's MagicDNS name (no DNS API token, nothing secret stored beyond the key nginx already uses) and installs it as `/etc/timecanvas/certificates/timecanvas.{crt,key}`. `timecanvas-tailscale-cert.timer` runs it daily at ~03:30 and nginx is reloaded only when the cert changes; a cert nginx rejects is rolled back. The original self-signed pair is kept as `selfsigned.{crt,key}`.

- Needs **HTTPS Certificates** enabled on the tailnet's DNS page. Issuing publishes the hostname to public Certificate Transparency logs.
- Check: `sudo systemctl start timecanvas-tailscale-cert && journalctl -u timecanvas-tailscale-cert -n 5`.
- The cert only matches the `.ts.net` name; open the dashboard by that name, not the IP.
