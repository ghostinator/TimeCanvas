#!/bin/sh
# Idempotent: attach camera 05a3:9422 to VM 102 (USB2, no usb3) and start it. Run on pve-pueblo as root.
set -eu
VMID=102; ID=05a3:9422
[ "$(hostnamectl --static)" = "pve-pueblo" ] || { echo wrong host >&2; exit 1; }
[ "$(qm config $VMID | sed -n 's/^name: //p')" = "timecanvas" ] || { echo "VM $VMID is not timecanvas" >&2; exit 1; }
n=$(lsusb -d $ID | wc -l); [ "$n" -eq 1 ] || { echo "expected exactly 1 $ID, found $n" >&2; exit 1; }
qm config $VMID | grep -q "^usb0: host=$ID" || qm set $VMID -usb0 host=$ID
[ "$(qm status $VMID)" = "status: running" ] || qm start $VMID
qm config $VMID | grep -E '^usb'
