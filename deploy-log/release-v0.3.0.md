> **Snapshot as of v0.3.0 (2026-11-22).** A dated record that is not updated when the system changes. Current facts live in the owner files: `docs/ARCHITECTURE.md` (units, helper actions, migrations, system inventory), `docs/SECURITY.md` (what runs as root, secrets), `docs/CONFIGURATION.md` (settings), `deploy-log/test-results.md` (Current status) and `CHANGELOG.md`.

# Release v0.3.0

## What is in it
- **Alerts** (Settings > Alerts): Teams Power Automate webhook, email through the Postal HTTP API or SMTP, optional heartbeat ping; checks for camera offline, no new photos, disk, archive, services and certificate; confirmation, reminders and recovery messages; own timer. Setup in `docs/ALERTS.md`.
- **Editing** render jobs and sessions.
- Fixes found while testing: Cloudflare blocking Python's default User-Agent (error 1010), per-channel test buttons, tailnet/`http` heartbeat URLs.
- Migration `004_alerts.sql`.

## Verification run for this release
- Full test suite on the VM at deploy time.
- Deployed the tag to the VM; footer and `VERSION` show `v0.3.0`; no failed units.
- Simulated outage through the real alert path on 2026-11-22: alert opened about 4 minutes 20 seconds after the camera went offline and the recovery message followed 32 seconds after it returned; both accepted by Teams and Postal.
- Owner confirmed email, Teams (after a flow fix) and the heartbeat.

## Acceptance changes since v0.2.x
Test 7 through nginx with a login passed (2026-11-22); physical replug, mobile, playback and render progress confirmed by the owner; test 40 remains **waived, not run**. See `deploy-log/test-results.md`.

## Known issues at release time (fixed afterwards, see CHANGELOG Unreleased)
- Deploying a new commit with identical code restarted the web service and render worker.
- Switching alerts off also stopped the heartbeat ping.
- `scripts/secret-scan.sh` could only scan staged changes, so "scan passed" before a push checked nothing; a `--range` mode was added.
