#!/bin/sh
# Idempotent Tailscale install from the official apt repo (root, on VM). Does NOT authenticate; the owner runs `sudo tailscale up`.
set -eu
[ -f /usr/share/keyrings/tailscale-archive-keyring.gpg ] || curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg -o /usr/share/keyrings/tailscale-archive-keyring.gpg
[ -f /etc/apt/sources.list.d/tailscale.list ] || curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list -o /etc/apt/sources.list.d/tailscale.list
apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tailscale
systemctl enable --now tailscaled >/dev/null 2>&1
tailscale version | head -1
