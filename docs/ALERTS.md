# Alerts

TimeCanvas checks itself every minute (`timecanvas-alerts.timer`, a unit of its own so it still reports when capture, health or the dashboard stop) and messages you through **Microsoft Teams** (a Power Automate workflow webhook) and/or **email**. Configure it under **Settings > Alerts**.

## What it watches
| Check | Fires when | Default |
|---|---|---|
| Camera offline | the streamer reports the camera gone for 3+ minutes | on |
| No new photos | capture is expected (capture on, inside any session schedule) but no good photo for 10+ minutes, for any cause other than "camera offline" (timer dead, bad frames, disk-blocked) | on |
| Disk space | media disk at or above the warning (warning) or critical (critical) level | on |
| OneDrive archive | the last archive run failed | on |
| Services | ustreamer, web, render-worker, capture timer or health timer not active, or the health check silent for 3+ minutes | on |
| HTTPS certificate | expires in under 14 days (under 3 = critical) | on |

How it behaves: a problem must be seen on **two consecutive checks** before anything is sent (a restart or one bad sample stays quiet). You then get **one message**, a **reminder** every 6 hours (configurable, 1-72) while it is still open, a **new message if a warning becomes critical**, and a **recovery message** with the duration. If a channel fails to deliver, it is retried every minute and the failure is shown under *Recent messages*. If no channel is configured, nothing is retried or spammed; it just shows on the Alerts page.

## Teams (Power Automate) setup
1. In Teams open **Workflows** (or go to make.powerautomate.com) and create a new flow from blank, or use the template *Send webhook alerts to a chat*.
2. Trigger: **When a Teams webhook request is received**. Set *Who can trigger the flow* to **Anyone** (the URL itself is the secret).
3. Action: **Post card in a chat or channel**. *Post as* **Flow bot**; *Post in* **Chat with Flow bot** (a direct message) with yourself as *Recipient*, or pick a channel. Leave the other fields alone.
   - The **Adaptive Card** box must contain *only this one expression*, entered as an expression, not typed as text:
     1. Click into the **Adaptive Card** box, then click the **fx** button that appears (the *Expression* tab).
     2. Delete everything in the expression box and paste exactly this single line:

        ```
        triggerBody()?['attachments']?[0]?['content']
        ```
     3. Click **Update**. The box now shows a purple `fx` chip, not curly-brace JSON.
   - **Do not** paste the JSON example further down this page into the flow. It only shows what TimeCanvas *sends* to the trigger; the flow picks the card out of it with the expression above. If you see "This expression has a problem" or `{...}` in the box, the JSON was pasted by mistake: clear the box and redo the three steps.
   - **If your flow has a Condition step** (flows built from the template do), the **Post card in a chat or channel** action must exist on **both** the *If yes* and the *If no* branch, each with the same recipient and the same expression. A card step on only one branch means some alerts are silently dropped. (Found while setting this up for real: the first test failed because only one branch had the card step.)
4. Save the flow, then copy the **HTTP POST URL** from the trigger.
5. In TimeCanvas: Settings > Alerts > Microsoft Teams: tick *Send to Teams*, paste the URL, **Save**, then press **Test Teams**.

For reference only (do not paste into the flow): TimeCanvas posts the standard message-with-Adaptive-Card payload (`{"type":"message","attachments":[{"contentType":"application/vnd.microsoft.card.adaptive","content":{...}}]}`): a coloured title (red critical, amber warning, green recovered), the details, and host / time / event facts. Only `https` URLs on Power Automate / Teams workflow hosts (`*.logic.azure.com`, `*.powerplatform.com`, `*.webhook.office.com`, `*.office.com`) are accepted.

## Verification status of third-party steps
These services change their screens and behaviour; trust the service's own run history over this page if they disagree.

| Procedure | Status |
|---|---|
| Power Automate flow: webhook trigger, card expression, card step on both branches of the Condition | Verified 2026-11-22 (owner's tenant; the first attempt failed on exactly the two points above) |
| Postal HTTP API: server API key, verified From domain, server behind Cloudflare | Verified 2026-11-22 |
| Uptime Kuma Push monitor on the tailnet, port 3001: *Test heartbeat* succeeds | Verified 2026-11-22 (Kuma's own alert when pings stop was not exercised: Not verified) |
| healthchecks.io ping URL | Not verified |
| SMTP notes for Microsoft 365 and Gmail | Not verified |

## Email setup
Settings > Alerts > Email: tick *Send email*, choose the method, set the From address and up to 5 recipients.
- **Postal (HTTP API, recommended):** your Postal server's URL (for example `https://app.example.com`) and a **server API key** (in Postal: your server > Credentials, type *API*). TimeCanvas calls `POST /api/v1/send/message` with the key in the `X-Server-API-Key` header. The **From** address must belong to a domain verified on that Postal server, otherwise Postal refuses the message and the reason ("FromAddressNotVerified" etc.) appears in *Recent messages*. Create a dedicated credential for TimeCanvas so it can be revoked on its own.
- **SMTP:** server, port, security (STARTTLS 587, SSL/TLS 465, none), user and password. Microsoft 365 often has SMTP AUTH disabled for users and Gmail needs an app password.

Messages are plain text with the subject `[TimeCanvas] ALERT: Camera offline` (or `REMINDER`, `RECOVERED`). The API key / SMTP password are typed into the dashboard (never in chat or git) and stored as described under Secrets.

## Heartbeat (optional, recommended)
Nothing inside the VM can tell you the VM or its host is down. Give a monitoring service a push URL and TimeCanvas calls it every minute (GET); that service messages you when the calls **stop**. The pings continue when *Alerts on* is switched off (they report that the VM is alive, not that alerts are enabled); remove the URL to stop them. Any `http://` or `https://` URL works, including private and Tailscale addresses (loopback, link-local and multicast addresses are refused).
- **Uptime Kuma:** add a monitor of type **Push**, set its *Heartbeat interval* to about 90-120 s, and paste the push URL it shows, including the port, for example `http://100.x.x.x:3001/api/push/<token>?status=up&msg=OK&ping=`. The VM must be on the same tailnet (it is).
- **healthchecks.io:** paste the ping URL (`https://hc-ping.com/<uuid>`).

## Cloudflare and other firewalls
All outbound calls (Teams, Postal, heartbeat) send a `TimeCanvas-alerts/1.0` User-Agent. Python's default one is blocked by Cloudflare-fronted servers with *HTTP 403, error code: 1010*; a Postal server behind Cloudflare therefore needs this (it is built in).

## Secrets
The webhook URL, Postal API key, SMTP password and heartbeat URL are typed into the dashboard and stored in `/var/lib/timecanvas/alerts.json` (mode 0600, user `timecanvas`). They are never shown again (fields say "saved - leave blank to keep"), never written to the audit log or alert history, and not included in the config/DB backups; after a rebuild enter them again. Everything else (thresholds, switches, mail server, addresses) is in the database settings.

## Testing
Settings > Alerts > Test has one button per channel (**Test Teams**, **Test email**, **Test heartbeat**) plus **Test everything switched on**. Each tests that channel alone, with the *saved* settings (press Save first), and a channel can be tested before you switch it on. Failures show the reason, for example `Postal answered HTTP 403: error code: 1010` or `Postal refused the message: FromAddressNotVerified`.

## Operations
- Test: the buttons above, or `sudo systemctl start timecanvas-alerts` then `journalctl -u timecanvas-alerts -n 20`.
- State: `sudo -u timecanvas sqlite3 /var/lib/timecanvas/timecanvas.db "select key,status,opened_utc from alert_state"`.
- Stop alert messages: untick *Alerts on* (the heartbeat, if configured, keeps pinging).
- Stop everything including the heartbeat: `sudo systemctl stop timecanvas-alerts.timer`.
