#!/bin/sh
# Idempotent guest baseline (Phase 4). Run as root inside the timecanvas VM.
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq dist-upgrade
apt-get -y -qq install qemu-guest-agent ffmpeg v4l-utils ustreamer python3 python3-venv python3-pip \
  nginx sqlite3 curl jq ca-certificates openssl apache2-utils rsync logrotate usbutils
id timecanvas >/dev/null 2>&1 || useradd --system --home-dir /var/lib/timecanvas --shell /usr/sbin/nologin --groups video timecanvas
usermod -aG video timecanvas
# code/config: root-owned, not writable by the service user
install -d -m 0755 -o root -g root /opt/timecanvas /opt/timecanvas/app /opt/timecanvas/scripts /opt/timecanvas/migrations
install -d -m 0751 -o root -g timecanvas /etc/timecanvas; install -d -m 0750 -o root -g timecanvas /etc/timecanvas/camera-profiles /etc/timecanvas/nginx /etc/timecanvas/certificates
# state: service-owned
install -d -m 0750 -o timecanvas -g timecanvas /var/lib/timecanvas /var/log/timecanvas
for d in images videos videos/daily videos/weekly videos/monthly videos/custom thumbnails exports spool tmp lost-and-found; do
  install -d -m 0750 -o timecanvas -g timecanvas /srv/timecanvas/$d
done
chown timecanvas:timecanvas /srv/timecanvas; chmod 0750 /srv/timecanvas
mount -a; findmnt /srv/timecanvas -n -o SOURCE,FSTYPE
