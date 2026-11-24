#!/bin/sh
# Runs as root on the VM from the staged git archive (/tmp/tc-stage). Idempotent.
set -eu
S=/tmp/tc-stage
# --checksum + only data-transfer/deleted lines count: git archive stamps files with the commit date, so a new commit with identical
# content shows time-only (".f..t...") lines that must NOT restart the web service and render worker.
CODE_CHANGED=$(rsync -a -c --no-owner --no-group --delete --itemize-changes "$S/app/" /opt/timecanvas/app/ | grep -E '^(>f|<f|cf|\*deleting)' | head -1)
rsync -a --delete "$S/migrations/" /opt/timecanvas/migrations/
rsync -a --delete "$S/scripts/" /opt/timecanvas/scripts/
install -m 0644 -o root -g root "$S/VERSION" /opt/timecanvas/VERSION
chown -R root:root /opt/timecanvas/app /opt/timecanvas/migrations /opt/timecanvas/scripts
chmod -R go-w /opt/timecanvas
[ -f /etc/timecanvas/config.toml ] || install -m 0640 -o root -g timecanvas "$S/config/config.example.toml" /etc/timecanvas/config.toml
install -d -m 0755 /opt/timecanvas/config; install -m 0644 "$S/config/config.example.toml" /opt/timecanvas/config/
install -m 0644 "$S/requirements.txt" /opt/timecanvas/requirements.txt
[ -x /opt/timecanvas/venv/bin/python ] || python3 -m venv /opt/timecanvas/venv
new=$(sha256sum "$S/requirements.txt" | cut -d' ' -f1)
[ "$(cat /opt/timecanvas/venv/.req-sha 2>/dev/null)" = "$new" ] || { /opt/timecanvas/venv/bin/pip install -q -r "$S/requirements.txt" && echo "$new" > /opt/timecanvas/venv/.req-sha; }
UNITS_CHANGED=""
for u in "$S"/systemd/*.service "$S"/systemd/*.socket "$S"/systemd/*.timer; do
  [ -f "$u" ] || continue
  cmp -s "$u" "/etc/systemd/system/$(basename "$u")" || { UNITS_CHANGED="$UNITS_CHANGED $(basename "$u")"; install -m 0644 "$u" /etc/systemd/system/; }
done
systemctl daemon-reload
sh "$S/scripts/nginx-setup.sh"
# enable list is maintained here (units that must run at boot)
for u in $(cat "$S/systemd/enabled.list" 2>/dev/null); do systemctl enable --now "$u" >/dev/null 2>&1; done
# restart only what changed: ustreamer only when its own unit changed (never on app-only deploys, to keep the stream up);
# web/render-worker also when app code changed
for u in $(cat "$S/systemd/restart.list" 2>/dev/null); do
  case "$u" in timecanvas-ustreamer.service) want=0 ;; *) want=$([ -n "$CODE_CHANGED" ] && echo 1 || echo 0) ;; esac
  case " $UNITS_CHANGED " in *" $u "*) want=1 ;; esac
  [ "$want" = 1 ] && systemctl is-active -q "$u" && systemctl restart "$u" || true
done
echo "installed $(head -1 /opt/timecanvas/VERSION)"
