# Archive to OneDrive

Every night at 02:30 (America/Denver) `timecanvas-archive.timer` uploads, with [rclone](https://rclone.org/), to a folder on OneDrive:

- each **finished local day** as one stored (uncompressed) zip of its frames, `frames/YYYY/MM/YYYY-MM-DD.zip`, with a `manifest.json` inside;
- each **rendered video** as-is, `videos/<name>`.

Each upload is verified by size before it is recorded in the `archive_items` table. The archive **only uploads and checks**: it never deletes anything locally or on OneDrive. Today's frames are not archived until the day is over.

## One-time setup (work account)

1. On your Mac: `brew install rclone` (use the same version as the VM, `rclone version`), then `rclone authorize "onedrive"`. Sign in with the **work** account in the browser that opens and copy the token it prints. Do not paste the token anywhere except the VM prompt below.
2. On the VM: `ssh brandon@<vm> -t 'sudo sh /opt/timecanvas/scripts/archive-setup.sh'`. It installs the pinned rclone release (v1.76.0, checksum-verified; Debian's 1.60 is too old for OneDrive sign-in) and starts rclone's own setup; the on-screen steps tell you what to answer (name the remote `tcarchive`, "OneDrive for Business", paste the token).
3. In the dashboard open **Settings > Archive**: it should say *Connected*. Tick *Archive to OneDrive every night*, set the folder (default `tcarchive:TimeCanvas`) and press **Run now** to upload the backlog.

The token lives only in `/var/lib/timecanvas/rclone.conf` (mode 0600, user `timecanvas`). It is not in git, not in `/etc/timecanvas`, and not in the config/DB backups, so a restored VM needs step 2 again.

### If sign-in says "Need admin approval"
Work tenants often block rclone's built-in app. Ask IT to approve it, or have them (or you) register an app in Microsoft Entra ID: redirect URI `http://localhost:53682/`, delegated permissions `Files.ReadWrite` and `offline_access`, then give rclone that app's client id/secret when `rclone config` asks for `client_id` and `client_secret`.

## Verification status of third-party steps
| Procedure | Status |
|---|---|
| `rclone authorize "onedrive"` on a Mac, then the VM's `archive-setup.sh`, with a work (Microsoft 365) account | Verified 2026-11-22 (owner's tenant; the default rclone app was accepted without admin approval) |
| Installing the pinned rclone release on the VM (checksum-verified) | Verified 2026-11-19 |
| Registering your own Entra ID app when sign-in says "Need admin approval" | Not verified (not needed in the owner's tenant) |

## Retention
With *Keep frames until they are archived* on (default) the nightly cleanup (03:30) skips frames of days, and videos, that are not yet on OneDrive. If the disk reaches its critical threshold the wait is dropped, so a broken connection cannot fill the disk. Turn the option off to retain by age only.

## Getting data back
Download the day's zip from OneDrive and unzip it; the file names are the original frame names (local time with UTC offset). Nothing in the dashboard lets you browse the remote.

## Operations
- Status: Settings > Archive, or `journalctl -u timecanvas-archive -n 50`.
- Manual run: `sudo systemctl start timecanvas-archive` (or the **Run now** button).
- Privacy: the camera images leave the VM and live in your organisation's OneDrive, under its retention and sharing policies.
