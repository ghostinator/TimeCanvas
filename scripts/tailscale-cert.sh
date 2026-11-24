#!/bin/sh
# Fetch/renew the Let's Encrypt cert Tailscale issues for this node's MagicDNS name and install it for nginx.
# Root, on the VM. Needs "HTTPS Certificates" enabled in the tailnet admin console. The hostname is read at runtime, never stored in git.
# Safe to re-run: it only touches nginx when the cert changed, and rolls back if nginx rejects the new files.
set -eu
D=/etc/timecanvas/certificates
H=$(tailscale status --json | jq -r '.Self.DNSName // empty | rtrimstr(".")')
[ -n "$H" ] || { echo "tailscale has no DNS name (is it logged in, and is MagicDNS on?)" >&2; exit 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
tailscale cert --min-validity 720h --cert-file "$T/c.pem" --key-file "$T/k.pem" "$H"
[ "$(openssl x509 -in "$T/c.pem" -pubkey -noout | sha256sum)" = "$(openssl pkey -in "$T/k.pem" -pubout | sha256sum)" ] || { echo "cert and key do not match" >&2; exit 1; }
if cmp -s "$T/c.pem" $D/timecanvas.crt; then echo "cert for $H unchanged"; exit 0; fi
[ -e $D/selfsigned.crt ] || { cp -p $D/timecanvas.crt $D/selfsigned.crt; cp -p $D/timecanvas.key $D/selfsigned.key; }
cp -p $D/timecanvas.crt "$T/old.crt"; cp -p $D/timecanvas.key "$T/old.key"
install -m 0644 -o root -g root "$T/c.pem" $D/timecanvas.crt
install -m 0600 -o root -g root "$T/k.pem" $D/timecanvas.key
if nginx -t >/dev/null 2>&1; then systemctl reload nginx; echo "installed cert for $H: $(openssl x509 -in $D/timecanvas.crt -noout -enddate)"
else
  install -m 0644 "$T/old.crt" $D/timecanvas.crt; install -m 0600 "$T/old.key" $D/timecanvas.key
  echo "nginx rejected the new cert; restored the previous one" >&2; exit 1
fi
