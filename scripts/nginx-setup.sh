#!/bin/sh
# Idempotent nginx wiring (root, on VM, from /tmp/tc-stage). Creates an EMPTY htpasswd if missing => nobody can log in until the owner adds a user.
set -eu
S=/tmp/tc-stage
sh "$S/scripts/make-cert.sh"
[ -e /etc/timecanvas/nginx/htpasswd ] || { : > /etc/timecanvas/nginx/htpasswd; }
chown root:www-data /etc/timecanvas/nginx/htpasswd; chmod 0640 /etc/timecanvas/nginx/htpasswd
chmod 0751 /etc/timecanvas   # traverse-only so nginx workers can reach the htpasswd; files inside stay 0640/0750
chmod 0750 /etc/timecanvas/nginx; chgrp www-data /etc/timecanvas/nginx
install -m 0644 "$S/nginx/timecanvas-limits.conf" /etc/nginx/conf.d/timecanvas-limits.conf
install -m 0644 "$S/nginx/timecanvas.conf" /etc/nginx/sites-available/timecanvas
ln -sf /etc/nginx/sites-available/timecanvas /etc/nginx/sites-enabled/timecanvas
[ -e /etc/nginx/sites-enabled/default ] && mv /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default.disabled-by-timecanvas
nginx -t
systemctl enable nginx >/dev/null 2>&1; systemctl reload nginx || systemctl restart nginx
