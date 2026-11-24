#!/bin/sh
# One-time OneDrive connection for the archive. Run on the VM as root: sudo sh /opt/timecanvas/scripts/archive-setup.sh
# Installs rclone, then opens rclone's own interactive setup as the timecanvas user. YOU type the sign-in token there:
# it is stored only in /var/lib/timecanvas/rclone.conf (0600, timecanvas). It is never in git, backups, logs or chat.
set -eu
CONF=/var/lib/timecanvas/rclone.conf
# Debian ships rclone 1.60 (2022), too old for current OneDrive sign-in/tokens: install the pinned official release, verified by SHA-256.
RCLONE_VER=1.76.0
RCLONE_SHA256=9db7ee9b725bce7cdd195b9183449a4c6fb93cad3e6578e70b87c0bc7f6062e9   # rclone-v1.76.0-linux-amd64.deb
if [ "$(rclone version 2>/dev/null | head -1)" != "rclone v$RCLONE_VER" ]; then
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
  curl -fsSL -o "$T/rclone.deb" "https://github.com/rclone/rclone/releases/download/v$RCLONE_VER/rclone-v$RCLONE_VER-linux-amd64.deb"
  [ "$(sha256sum "$T/rclone.deb" | cut -d' ' -f1)" = "$RCLONE_SHA256" ] || { echo "rclone download failed its checksum; not installing" >&2; exit 1; }
  dpkg -i "$T/rclone.deb"
fi
install -d -o timecanvas -g timecanvas -m 0700 /var/lib/timecanvas/cache
[ -e "$CONF" ] || install -o timecanvas -g timecanvas -m 0600 /dev/null "$CONF"
cat <<'TXT'

On your Mac first (needs rclone: brew install rclone):   rclone authorize "onedrive"
It opens a browser: sign in with your WORK account. Copy the token it prints ({"access_token": ... }).

Then answer rclone's questions below:
  n) New remote            name> tcarchive            Storage> onedrive
  client_id / client_secret> (empty, unless your IT team gave you an app)    region> 1 (Microsoft Cloud Global)
  Edit advanced config?> n
  Use web browser to automatically authenticate?> n   -> paste the token from your Mac when asked
  Type of connection> OneDrive for Business   -> pick your drive   -> y (keep)   -> q (quit)
TXT
printf '\nPress Enter to start rclone config...'; read _
sudo -u timecanvas env XDG_CACHE_HOME=/var/lib/timecanvas/cache rclone --config "$CONF" config
# the dashboard expects the remote to be called tcarchive: if exactly one other remote was created, rename it
if ! grep -q '^\[tcarchive\]' "$CONF" && [ "$(grep -c '^\[' "$CONF")" = 1 ]; then
  sed -i 's/^\[[^]]*\]/[tcarchive]/' "$CONF"; chown timecanvas:timecanvas "$CONF"; chmod 0600 "$CONF"; echo "(renamed your remote to tcarchive)"
fi
echo; echo "Testing the connection..."
sudo -u timecanvas env XDG_CACHE_HOME=/var/lib/timecanvas/cache rclone --config "$CONF" lsd tcarchive: && echo "OK: connected. Turn the archive on in the dashboard: Settings > Archive."
