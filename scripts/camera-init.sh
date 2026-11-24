#!/bin/sh
# Apply only the controls the camera actually has; log each change. Fails cleanly if the camera is missing.
# Order: power_line_frequency default, then saved dashboard values (/etc/timecanvas/camera-controls.json, auto-mode controls first).
set -eu
DEV=${TC_DEVICE:-/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0}
SAVED=${TC_CONTROLS:-/etc/timecanvas/camera-controls.json}
for i in $(seq 1 15); do [ -e "$DEV" ] && break; sleep 1; done
[ -e "$DEV" ] || { echo "camera-init: device $DEV missing" >&2; exit 1; }
ctrls=$(v4l2-ctl -d "$DEV" --list-ctrls 2>/dev/null || true)
set_ctrl() {
  echo "$ctrls" | grep -q "^ *$1 " || { echo "camera-init: control $1 not present, skipped"; return 0; }
  v4l2-ctl -d "$DEV" --set-ctrl="$1=$2" 2>/dev/null && echo "camera-init: set $1=$2" || echo "camera-init: $1=$2 not applied (inactive?)"
}
set_ctrl power_line_frequency "${TC_POWER_LINE:-2}"
apply_saved() {  # $1 = jq filter selecting "name value" lines
  jq -r "$1" "$SAVED" 2>/dev/null | while read -r k v; do
    case "$k" in ''|*[!a-z0-9_]*) continue ;; esac
    set_ctrl "$k" "$v"
  done
}
if [ -s "$SAVED" ]; then
  # auto_exposure / white_balance_automatic first so the manual values they unlock can be set
  apply_saved 'to_entries[] | select(.key=="auto_exposure" or .key=="white_balance_automatic") | select(.value|type=="number") | "\(.key) \(.value)"'
  apply_saved 'to_entries[] | select(.key!="auto_exposure" and .key!="white_balance_automatic") | select(.value|type=="number") | "\(.key) \(.value)"'
fi
echo "camera-init: done"
