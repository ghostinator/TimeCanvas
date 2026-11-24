#!/bin/sh
# Apply the VM firewall with an automatic rollback: if you do not confirm within 180 s, the previous ruleset is restored.
# Usage (root, on VM):  firewall-apply.sh        -> applies, schedules rollback
#                       firewall-apply.sh keep   -> cancels rollback and persists rules across reboot
set -eu
RULES=/etc/timecanvas/firewall.nft; PREV=/root/nft-previous.nft
if [ "${1:-}" = "keep" ]; then
  systemctl stop timecanvas-fw-rollback.timer 2>/dev/null || true
  systemctl enable nftables >/dev/null 2>&1
  cp "$RULES" /etc/nftables.conf; chmod 0644 /etc/nftables.conf
  echo "firewall persisted; rollback cancelled"; exit 0
fi
install -m 0644 /tmp/tc-stage/infra/vm/nftables-timecanvas.nft "$RULES"
nft list ruleset > "$PREV"
nft -c -f "$RULES"
systemctl stop timecanvas-fw-rollback.timer 2>/dev/null || true
systemd-run --unit=timecanvas-fw-rollback --on-active=180 /bin/sh -c "nft flush ruleset; nft -f $PREV" >/dev/null
nft -f "$RULES"
echo "applied. Confirm SSH + https still work, then run: sudo sh /opt/timecanvas/scripts/firewall-apply.sh keep  (rollback in 180 s)"
