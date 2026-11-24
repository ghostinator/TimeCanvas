# Troubleshooting
| Symptom | Check |
|---|---|
| Feed black / "OFFLINE" | `curl -s localhost:8080/state` in the VM; `lsusb` shows 05a3:9422? `journalctl -u timecanvas-ustreamer`; Camera page -> Rescan. Passthrough: on the host `qm config 102 | grep usb`. |
| Frames drop or the feed stutters at 1080p | Almost always cabling or a bad hub (USB -71 errors in `journalctl -k`, see CAMERA_CAPABILITIES). Try a shorter/direct cable first; the Camera page can drop to 720p@15, which was always stable. |
| Captures `failed: camera offline` | placeholder frame rejected by design; fix camera first. |
| `blocked_disk` events | disk >= 90 %: free space (Maintenance -> retention dry run, or lower retention), nothing is auto-deleted. |
| Library empty after restore | run reconcile; confirm `/srv/timecanvas` is mounted (`findmnt`). |
| Render "failed" | job error text on Renders page; `journalctl -u timecanvas-render-worker`. Retry re-queues. |
| Can't log in | `sudo htpasswd -B /etc/timecanvas/nginx/htpasswd <user>` |
| Locked out by firewall | wait 180 s for auto-rollback, or use the Proxmox console and `nft flush ruleset`. |
| Dashboard 401 | missing login (nginx) |
| Archive says "Not set up" | run `sudo sh /opt/timecanvas/scripts/archive-setup.sh`; the remote must be named `tcarchive`; check `sudo -u timecanvas rclone --config /var/lib/timecanvas/rclone.conf lsd tcarchive:` |
| Archive "Failed" with token/auth text | the OneDrive token expired or was revoked: re-run the setup script. "Need admin approval" at sign-in: see docs/ARCHIVE.md |
| Archive "verification failed" | the uploaded size differed from the zip; it is retried next run, nothing is marked archived |
| Frames not being deleted | with "keep until archived" on, retention waits for unarchived days; check Settings > Archive (the wait is dropped only at the critical disk level) |
| Browser warns about the certificate | you used the IP address; use the `.ts.net` name. If that also warns: `systemctl status timecanvas-tailscale-cert`, and HTTPS Certificates must be enabled in the tailnet |
| Renders page FPS empty / "invalid" | fixed in v0.1.0 (the form now passes the default fps); redeploy |
| Render fails "ffprobe check failed" | a frame-count mismatch (fixed in v0.1.0 by `-frames:v`); check the job error and `journalctl -u timecanvas-render-worker` |
| Dropdown or control does nothing | the CSP blocks inline handlers by design; hard-reload (the bundled scripts are cached) |
| Postal test says `HTTP 403 ... error code: 1010` | Cloudflare blocking Python's default User-Agent; fixed (TimeCanvas sends its own). If you still see 403 with other text, the text is the reason |
| Postal says `InvalidServerAPIKey` | the key is wrong or is not an *API*-type credential of that Postal server; create an API credential under the server's Credentials page |
| Heartbeat test fails | use the push URL including its port (Uptime Kuma is usually `:3001`), and check `curl -m 5 <url>` from the VM |
| Teams test says OK but nothing arrives in Teams | TimeCanvas only knows Power Automate *accepted* the request. Open the flow's **Run history**: a red run means the card step failed, usually because the *Adaptive Card* box does not contain exactly the expression `triggerBody()?['attachments']?[0]?['content']` (see docs/ALERTS.md step 3) |
| Some Teams alerts arrive and others do not | the flow has a Condition and the card step is only on one branch; add the same *Post card* action (same expression, same recipient) to both *If yes* and *If no* |
| "This expression has a problem" in the flow | the example JSON was pasted into the Adaptive Card box; clear it and enter only the expression via the fx tab |
| No alert arrived | Settings > Alerts > Recent messages shows delivery results; use the **Test Teams** / **Test email** / **Test heartbeat** buttons. A failed Teams delivery usually means the flow was turned off or its URL changed; the flow's run history in Power Automate shows why |
| Alert arrives late | a problem must be seen on two consecutive minute checks, and the camera/photo checks have their own minute thresholds (3 and 10 by default) |
| "No new photos" at the start of a scheduled window | should not happen (it waits one threshold after the window opens); if it does, check the session's days/hours |
