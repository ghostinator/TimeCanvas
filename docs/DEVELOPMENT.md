# Development

## Git flow
- `main` is releasable. Work happens on `feat/*`, `fix/*`, `docs/*` branches merged with `--no-ff` after the tests pass.
- Conventional Commits (`feat`, `fix`, `chore`, `docs`, `test`, `infra`). Never rewrite pushed history.
- Nobody hand-edits files on the VM. If an emergency edit is unavoidable, copy it back into the repo and commit it immediately.
- Host-changing commands live in `infra/proxmox/` and are shown (with a `--dry-run`) before they run.

## Tests
Run the whole suite from the repo root:

```bash
python3 -m unittest discover -s tests
```

| File | Covers |
|---|---|
| `test_core.py` | paths, JPEG validation, filenames and DST, disk thresholds, migrations |
| `test_render_cleanup.py` | render pipeline with real ffmpeg, retention, DST day ranges |
| `test_files.py` | bulk actions, zips, per-day stats |
| `test_camera.py` | V4L2 parsing, camera mode and control validation |
| `test_archive.py` | OneDrive archive against a fake `rclone` |
| `test_alerts.py` | alert engine (confirmation, reminders, recovery, schedules), Postal/Teams/SMTP payloads, validation |
| `test_web.py` | auth, CSRF, navigation, library, play, archive, alerts, editing jobs and sessions, no inline handlers (needs `fastapi` + `httpx`, otherwise skipped) |
| `test_docs.py` | documentation drift checks (see below); stdlib only, never skipped |

`tests/live/` holds probes that need the real camera (`livetest.py`, `modeprobe.py`) and the 30-minute nginx soak (`soak_nginx.py`, run by the owner because it needs the login). The VM runs the full suite with a venv from `requirements-dev.txt`. Browser behaviour (selection, viewer) was checked by driving a static page with the same markup in a real browser.

## Secret scan
- The pre-commit hook (`git config core.hooksPath .githooks`) runs `scripts/secret-scan.sh`, which scans **staged additions only**.
- Before pushing, scan every commit you are about to publish:

```bash
scripts/secret-scan.sh --range origin/main..HEAD
```

- The whole history can be scanned with `--range --all`. A clean working tree makes the default mode scan nothing, so the default mode is not a pre-push check.
- A line may carry `secret-scan: allow` for a false positive, only after inspecting it.

## Deploy and release
1. `TC_HOST=user@vm-address scripts/deploy.sh [ref]` (clean tree required; `TC_HOST` has no default): `git archive`, rsync to `/tmp/tc-stage`, `scripts/install.sh`, then `/opt/timecanvas/VERSION` = `git describe` + commit.
2. `install.sh` restarts only what really changed: web and render-worker when app code changed in content, ustreamer only when its own unit changed. A new commit with identical code restarts nothing.
3. To release: update `CHANGELOG.md`, tag annotated `vX.Y.Z` on a clean, tested `main`, `scripts/deploy.sh vX.Y.Z`, check the footer shows the tag, redeploy and confirm nothing changes, then push with tags.
4. Roll back by deploying an earlier tag: `scripts/deploy.sh v0.1.0`.

## Documentation standard
Docs are part of the change: a feature is not done until the owner files below describe it. `tests/test_docs.py` enforces what a machine can check.

**P1. One owner file per volatile fact; other files link to it.**

| Owner | Facts it owns |
|---|---|
| `ARCHITECTURE.md` | units and timers, helper actions, migrations, system inventory (node, VM, disks, USB, camera path, package versions) |
| `CONFIGURATION.md` | every settings key with range and default |
| `SECURITY.md` | what runs as root, the secrets inventory (location, backed up or not), controls |
| `deploy-log/test-results.md` | acceptance status (Current status table) |
| `CHANGELOG.md` | what each release contains |

Do not write test counts anywhere in `docs/` or the README; describe coverage instead.

**P2. Snapshots are immutable.** Files in `deploy-log/` that are dated or tied to a release start with a "Snapshot as of <tag>" banner pointing to the owner files. Their bodies change only through a dated "Correction" section; a new release gets a new thin `release-vX.Y.Z.md` that links to the owners instead of repeating them.

**P3. `test-results.md` has a Current status table** with one row per acceptance test 1-46 plus the extras, then the full "History" below. Never upgrade a result beyond its evidence: user-reported results stay marked user-reported, and a pass states what it did not check (test 40 passed with limits: guests and host-side state were not inspected).

**P4. UI text in docs matches the templates exactly.** After renaming a label or tab, search the docs for the old text.

**P5. Third-party procedures** (Power Automate, Postal, Uptime Kuma, Tailscale admin, Microsoft sign-in) say "Verified YYYY-MM-DD" or "Not verified".

**P6. Format.** One topic per heading, numbered steps for procedures, one command per fenced block, tables for reference material, short paragraphs.

**P7. Run the docs test** (`tests/test_docs.py`) with the rest of the suite; its failures say exactly which owner file to update.

## Screenshots
`docs/images/*.jpg` are real captures of a running install, used by the README and the user guide. JPEG (quality 80) keeps the repository small; `.gitignore` excludes other `*.jpg` files but allows this folder.

To retake them after a UI change, without touching the login:
1. Tunnel to the dashboard and the streamer on the VM: `ssh -N -L 18000:127.0.0.1:8000 -L 18080:127.0.0.1:8080 <admin>@<vm>`. The app listens on loopback only; nginx normally adds the user name.
2. Drive the pages with a browser tool (Playwright) at 1360 x 900 (390 x 844 for mobile), sending the header `X-Remote-User: admin` yourself. Only read-only pages are captured.
3. The live feed is served by nginx, not the app, so answer `/live/stream` with one JPEG fetched from `http://127.0.0.1:18080/snapshot`.
4. Click Load on the Play tab and click the first thumbnail on the Library tab before capturing those two.
5. Look at every image before committing: nothing should show a real user name, address or secret. The camera frames are not sensitive for this install; check yours.
