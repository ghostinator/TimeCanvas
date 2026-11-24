#!/bin/sh
# Make TimeCanvas (VM 102) start by itself when pve-pueblo boots. Touches ONLY VM 102's config: `qm set 102 --onboot 1 --startup down=120`.
# It does not touch VMs 103/104, LXC 105, host networking, storage, firewall or cluster services.
# Run ON pve-pueblo as root:   sh set-vm-autostart.sh --dry-run   (shows what would change)   then   sh set-vm-autostart.sh
# Undo:                        qm set 102 --onboot 0 --delete startup
set -eu
VMID=102
[ "$(hostnamectl --static)" = "pve-pueblo" ] || { echo "refusing: this is not pve-pueblo" >&2; exit 1; }
qm config $VMID | grep -q '^name: timecanvas$' || { echo "refusing: VM $VMID is not 'timecanvas'" >&2; exit 1; }
echo "before: $(qm config $VMID | grep -E '^(onboot|startup):' | tr '\n' ' ')(onboot missing/0 means no autostart)"
# No startup order or delay is set, so the other guests' boot order and timing (103/104/105 autostart with defaults) are not affected.
# down=120 only gives THIS VM up to 120 s to shut down cleanly.
CMD="qm set $VMID --onboot 1 --startup down=120"
if [ "${1:-}" = "--dry-run" ]; then echo "would run: $CMD"; exit 0; fi
$CMD
echo "after:  $(qm config $VMID | grep -E '^(onboot|startup):' | tr '\n' ' ')"
echo "usb0:   $(qm config $VMID | grep '^usb0:')  (passthrough is by ID and persists across host reboots)"
