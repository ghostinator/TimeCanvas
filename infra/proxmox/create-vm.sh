#!/bin/sh
# Idempotent creation of VM 102 "timecanvas" on pve-pueblo. Run ON the Proxmox host as root.
# Usage: create-vm.sh [--dry-run]   (needs /root/timecanvas-admin.pub = the admin's PUBLIC key)
# Touches only VMID 102, the image/snippet files named below. Never touches 103/104/105, network, storage.cfg.
set -eu
VMID=102; NAME=timecanvas; BRIDGE=vmbr0; STORE=local-lvm
IMG_URL=https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2
SUMS_URL=https://cloud.debian.org/images/cloud/trixie/latest/SHA512SUMS
IMG_DIR=/var/lib/vz/template/timecanvas; IMG=$IMG_DIR/debian-13-generic-amd64.qcow2
SNIP=/var/lib/vz/snippets/timecanvas-user.yaml
PUB=/root/timecanvas-admin.pub; TMPL=/root/timecanvas-user-data.tmpl.yaml
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
run() { echo "+ $*"; [ $DRY -eq 1 ] || "$@"; }

[ "$(hostnamectl --static)" = "pve-pueblo" ] || { echo "wrong host" >&2; exit 1; }
if qm status $VMID >/dev/null 2>&1; then
  [ "$(qm config $VMID | sed -n 's/^name: //p')" = "$NAME" ] && { echo "VM $VMID already exists as $NAME; nothing to do."; exit 0; }
  echo "VMID $VMID is used by something else; abort" >&2; exit 1
fi
[ -s $PUB ] && grep -q '^ssh-' $PUB && ! grep -q PRIVATE $PUB || { echo "need a public key at $PUB" >&2; exit 1; }
[ -s $TMPL ] || { echo "missing $TMPL" >&2; exit 1; }

run mkdir -p $IMG_DIR
if [ ! -s $IMG ]; then
  run curl -fsSL -o $IMG.part $IMG_URL
  if [ $DRY -eq 0 ]; then
    want=$(curl -fsSL $SUMS_URL | awk '/debian-13-generic-amd64.qcow2$/{print $1}')
    got=$(sha512sum $IMG.part | awk '{print $1}')
    [ -n "$want" ] && [ "$want" = "$got" ] || { echo "CHECKSUM MISMATCH; aborting" >&2; rm -f $IMG.part; exit 1; }
    mv $IMG.part $IMG; echo "checksum OK"
  fi
fi
if [ $DRY -eq 0 ]; then
  [ -f $SNIP ] && cp -a $SNIP $SNIP.bak.$(date +%s)
  KEY=$(cat $PUB); sed "s|@SSH_PUBKEY@|$KEY|" $TMPL > $SNIP
fi
echo "+ render $SNIP"
run qm create $VMID --name $NAME --machine q35 --bios seabios --ostype l26 --cores 2 --memory 2048 \
  --cpu host --scsihw virtio-scsi-single --net0 virtio,bridge=$BRIDGE --agent enabled=1 \
  --serial0 socket --vga serial0 --onboot 0 --protection 0
run qm set $VMID --scsi0 $STORE:0,import-from=$IMG,discard=on,ssd=1
run qm resize $VMID scsi0 24G
run qm set $VMID --scsi1 $STORE:256,discard=on,ssd=1,backup=0
run qm set $VMID --ide2 $STORE:cloudinit --boot order=scsi0
run qm set $VMID --cicustom user=local:snippets/timecanvas-user.yaml --ipconfig0 ip=dhcp
echo "Created VM $VMID (not started; USB passthrough is a separate script)."
