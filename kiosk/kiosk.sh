#!/bin/sh
# Kiosk for one seat: cage (Wayland) + Chromium, drawing only on this seat's GPU.
# Usage: kiosk.sh <seat-id>   (run by pve-homelab-kiosk@<seat-id>.service)
set -eu
SEAT="$1"
URL="http://127.0.0.1:8900/?seat=$SEAT"
read -r GPU DEBUG_PORT <<EOF
$(python3 -c "
import yaml, sys
c = yaml.safe_load(open('/etc/pve-homelab/config.yaml'))
print(c['seats'][sys.argv[1]]['gpu'], int((c.get('kiosk') or {}).get('debug_port') or 0))" "$SEAT")
EOF
DEBUG_ARGS=""
[ "$DEBUG_PORT" -gt 0 ] && DEBUG_ARGS="--remote-debugging-address=127.0.0.1 --remote-debugging-port=$DEBUG_PORT"

CARD="$(ls "/sys/bus/pci/devices/$GPU/drm" | grep -m1 '^card')"
[ -n "$CARD" ] || { echo "no DRM card for $GPU" >&2; exit 1; }
export WLR_DRM_DEVICES="/dev/dri/$CARD"
export WLR_LIBINPUT_NO_DEVICES=1
export XDG_SESSION_TYPE=wayland

# Wait for the backend so the first paint is the real menu, not an error page.
i=0
while ! python3 -c "import urllib.request;urllib.request.urlopen('$URL',timeout=1)" 2>/dev/null; do
  i=$((i+1)); [ $i -gt 60 ] && break; sleep 1
done

PROFILE="$HOME/chromium/$SEAT"
mkdir -p "$PROFILE"
# A crash must not leave the "restore pages?" bubble on screen.
# Chromium keeps the extension's old service worker code across restarts; always start from the files on disk.
rm -rf "$PROFILE/Default/Service Worker"
sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' \
  "$PROFILE/Default/Preferences" 2>/dev/null || true

exec cage -s -- chromium \
  --ozone-platform=wayland \
  --kiosk "$URL" \
  --user-data-dir="$PROFILE" \
  --load-extension=/opt/pve-homelab/kiosk/ext \
  --no-first-run --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --password-store=basic \
  --disable-features=Translate,MediaRouter,HardwareMediaKeyHandling,DisableLoadExtensionCommandLineSwitch \
  --check-for-update-interval=31536000 --overscroll-history-navigation=0 \
  --disable-pinch --autoplay-policy=no-user-gesture-required \
  $DEBUG_ARGS
