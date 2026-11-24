#!/bin/sh
# Idempotent self-signed cert for the dashboard. Run as root on the VM. Key never leaves the VM / never in git.
set -eu
D=/etc/timecanvas/certificates
[ -s $D/timecanvas.crt ] && [ -s $D/timecanvas.key ] && { echo "cert exists"; exit 0; }
IP=$(hostname -I | awk '{print $1}')
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 -subj "/CN=timecanvas" \
  -addext "subjectAltName=DNS:timecanvas,DNS:timecanvas.local,IP:$IP" -keyout $D/timecanvas.key -out $D/timecanvas.crt 2>/dev/null
chown root:root $D/timecanvas.key $D/timecanvas.crt; chmod 0600 $D/timecanvas.key; chmod 0644 $D/timecanvas.crt
echo "created self-signed cert for $IP"
