# Security

Owner of: what runs as root, the secrets inventory, and the controls that protect the dashboard.

## Network exposure
- Nginx is the only listener reachable from the LAN (port 80 redirects to 443). `ustreamer` (:8080) and `uvicorn` (:8000) bind to 127.0.0.1.
- nftables: input default-deny; SSH/80/443 only from `192.168.1.0/24` and the owner's Mac on the tailnet.
- Proxmox: no TimeCanvas key was added to the cluster `authorized_keys`, and no Proxmox credential is stored in the VM.

## Authentication
- Basic Auth over TLS protects the dashboard, media and `/live/stream`. The htpasswd is created interactively by the owner on the VM; nginx starts with an empty file, so nobody can log in until it is filled.
- The app additionally refuses any request without `X-Remote-User`, which only nginx sets.

## Web application controls
- CSRF: double-submit cookie (`tc_csrf`, Secure, SameSite=Strict) plus an Origin check on every state-changing request.
- Headers and limits: nosniff, frame-deny, `Content-Security-Policy: default-src 'self'; script-src 'self'`, POST rate limits, 64 KB body limit.
- There are no inline handlers or scripts anywhere (a test checks every page). htmx and the font are vendored; htmx runs with `allowEval:false, selfRequestsOnly:true`.
- The dashboard has no shell, command, file-browse, raw SQL, arbitrary FFmpeg or systemd surface. Media is served only by database id, resolved through `safe_path` (symlink- and traversal-proof).

## What runs as root
Everything TimeCanvas runs is user `timecanvas` except the units below. All have a fixed, narrow job.

| Unit | Why root | Limits |
|---|---|---|
| `helper@.service` (socket-activated by `helper.socket`) | restarts the streamer, sets camera controls and mode, starts the archive unit, reads journals | JSON allowlist of actions (listed in ARCHITECTURE), argument validation, `ProtectSystem=strict` (writes only `/etc/timecanvas`), capabilities limited to `CAP_DAC_OVERRIDE`, `CAP_DAC_READ_SEARCH`, `CAP_CHOWN` and `CAP_FOWNER` |
| `backup.service` (oneshot, 04:00) | reads `/etc/timecanvas` | `ProtectSystem=strict`, writes only `/var/backups` and `/var/lib/timecanvas` (the database backup needs the latter) |
| `tailscale-cert.service` (oneshot, daily) | writes the certificate and key, reloads nginx | lighter sandbox (`NoNewPrivileges`, `PrivateTmp`, `ProtectHome`); rolls back a certificate nginx rejects |

Outside TimeCanvas, the nginx master process (workers run as `www-data`), `tailscaled`, `sshd` and systemd also run as root. The web unit has `NoNewPrivileges`, an empty capability set, no device access, and cannot write to `/opt/timecanvas`.

## Secrets inventory
| Secret | Location | In the config/DB backup |
|---|---|---|
| Dashboard login hashes | `/etc/timecanvas/nginx/htpasswd` (root:www-data, 0640) | yes |
| TLS private key | `/etc/timecanvas/certificates/timecanvas.key` (root, 0600), plus `selfsigned.key` | yes (re-issued daily by the cert timer anyway) |
| OneDrive token | `/var/lib/timecanvas/rclone.conf` (timecanvas, 0600) | **no**; re-run `scripts/archive-setup.sh` after a rebuild |
| Teams webhook URL, Postal API key, SMTP password, heartbeat URL | `/var/lib/timecanvas/alerts.json` (timecanvas, 0600) | **no**; re-enter them on Settings > Alerts |
| Tailscale node key | managed by `tailscaled` | no |

Treat copies of `/var/backups/timecanvas` as secrets (they hold the htpasswd and TLS key). No private SSH keys live on the VM. None of the above is in git or in logs.

## Secret scanning
- The pre-commit hook scans staged additions with `scripts/secret-scan.sh`. A clean working tree has nothing staged, so the default mode is **not** a pre-push check.
- Before pushing, run `scripts/secret-scan.sh --range origin/main..HEAD`; the whole history can be scanned with `--range --all`.

## TLS
- A Let's Encrypt certificate issued by `tailscale cert` for the node's MagicDNS name is installed in `/etc/timecanvas/certificates/` and renewed daily by `timecanvas-tailscale-cert.timer`.
- The original self-signed pair is kept as `selfsigned.*`. You meet it only when you use the IP address (name-mismatch warning).
- Issuing publishes the hostname to Certificate Transparency logs. No DNS API token is used or stored.

## Archive (OneDrive)
- `rclone` runs as `timecanvas` with `--config /var/lib/timecanvas/rclone.conf` and only `listremotes`, `copyto` and `lsjson`.
- The remote string is validated (`name:path`, name starts alphanumeric, no `..`, nothing option-like) and never passes through a shell.
- The OneDrive token is created by the owner at the VM prompt. The archive cannot delete anything locally or remotely; the dashboard "Run now" goes through the helper allowlist (`archive-run`, which starts one fixed unit).
- Data leaves the VM only through the archive, into the organisation's OneDrive, under that tenant's retention and sharing policy.
- Retention can wait for the archive, but drops the wait at the critical disk threshold, so a failing archive cannot fill the disk.

## Alerts
- Secrets live only in `alerts.json` (see the inventory), are never rendered back, and never enter the audit log or alert history. Delivery errors and HTTP error bodies are stored scrubbed of URLs, keys and passwords.
- Teams webhooks must be `https` on a Power Automate / Teams workflow host, with no credentials or odd port. The Postal server must be an `https` URL to a public host name.
- The heartbeat must be an `http(s)` URL without credentials whose host is not loopback, link-local (cloud metadata), multicast or unspecified. Private and tailnet addresses are allowed on purpose.
- Outbound calls do not follow redirects (limits SSRF) and send a `TimeCanvas-alerts/1.0` User-Agent.
- The alerts unit runs as `timecanvas` with the same sandbox as the archive unit and write access only to `/var/lib/timecanvas`.
