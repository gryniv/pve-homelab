#!/bin/bash
# PVE Seat installer for a Proxmox VE host. Run as root from the repository:
#
#   ./install.sh               install or update
#   ./install.sh --no-kiosk    backend only (no menu on the local screens)
#   ./install.sh --city Lviv --lang en    hints for the first-run config
#
# Safe to re-run: /etc/pve-seat/config.yaml and per-user settings are never overwritten.
set -euo pipefail
cd "$(dirname "$0")"

KIOSK=1
SETUP_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-kiosk) KIOSK=0 ;;
    --city|--lang) SETUP_ARGS+=("$1" "$2"); shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
command -v pveversion >/dev/null || { echo "This is not a Proxmox VE host"; exit 1; }
PVE_MAJOR=$(pveversion | sed -n 's#^pve-manager/\([0-9]*\).*#\1#p')
[ "${PVE_MAJOR:-0}" -ge 8 ] || { echo "Proxmox VE 8 or newer is required (found $(pveversion))"; exit 1; }

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
PKGS="python3-aiohttp python3-yaml ddcutil"
[ "$KIOSK" = 1 ] && PKGS="$PKGS cage chromium fonts-noto-color-emoji"
apt-get install -y --no-install-recommends $PKGS >/dev/null

echo "==> Kiosk user"
if ! id pveseat >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pve-seat --shell /usr/sbin/nologin pveseat
fi
usermod -aG video,render,input pveseat

echo "==> Program files -> /opt/pve-seat"
install -d /opt/pve-seat /etc/pve-seat/users /var/cache/pve-seat
rm -rf /opt/pve-seat/backend /opt/pve-seat/web /opt/pve-seat/kiosk
cp -r backend web kiosk /opt/pve-seat/
[ -f VERSION ] && cp VERSION /opt/pve-seat/
chown -R root:root /opt/pve-seat
chmod -R u=rwX,go=rX /opt/pve-seat
chmod 755 /opt/pve-seat/kiosk/kiosk.sh
find /opt/pve-seat -name __pycache__ -prune -exec rm -rf {} +

echo "==> DDC (monitor input switching)"
echo i2c-dev > /etc/modules-load.d/pve-seat.conf
modprobe i2c-dev || true

if [ ! -f /etc/pve-seat/config.yaml ]; then
  echo "==> First run: detecting GPUs, monitors and Caddy"
  (cd /opt/pve-seat/backend && python3 -m pveseat.setup --write /etc/pve-seat/config.yaml "${SETUP_ARGS[@]}")
fi
chmod 644 /etc/pve-seat/config.yaml

if [ "$KIOSK" = 1 ]; then
  echo "==> Chromium policy (system DNS, no sign-in, no translate)"
  install -d /etc/chromium/policies/managed
  cp kiosk/chromium-policy.json /etc/chromium/policies/managed/pve-seat.json
fi

echo "==> Services"
cp systemd/pve-seat.service systemd/pve-seat-kiosk@.service /etc/systemd/system/
SEATS=$(python3 -c "
import yaml
c = yaml.safe_load(open('/etc/pve-seat/config.yaml')) or {}
for sid, s in (c.get('seats') or {}).items():
    if s.get('kiosk'): print(sid, s.get('tty', 7))
")
systemctl daemon-reload
systemctl enable --now pve-seat.service >/dev/null
systemctl restart pve-seat.service

if [ "$KIOSK" = 1 ]; then
  while read -r sid tty; do
    [ -n "$sid" ] || continue
    d=/etc/systemd/system/pve-seat-kiosk@$sid.service.d
    install -d "$d"
    cat > "$d/seat.conf" <<EOF
[Unit]
Conflicts=getty@tty$tty.service
After=getty@tty$tty.service

[Service]
TTYPath=/dev/tty$tty
ExecStartPre=+/usr/bin/chvt $tty
EOF
  done <<< "$SEATS"
  systemctl daemon-reload
  while read -r sid tty; do
    [ -n "$sid" ] || continue
    systemctl enable pve-seat-kiosk@"$sid".service >/dev/null 2>&1
    systemctl restart pve-seat-kiosk@"$sid".service
    echo "    menu on seat '$sid' (tty$tty)"
  done <<< "$SEATS"
  [ -n "$(echo "$SEATS" | tr -d '[:space:]')" ] || echo "    no seats in /etc/pve-seat/config.yaml: no GPU with a monitor was found"
fi

echo
echo "Done. Text console: Ctrl+Alt+F1, menu: Ctrl+Alt+F7."
echo "Config: /etc/pve-seat/config.yaml   Logs: journalctl -u pve-seat -u 'pve-seat-kiosk@*' -f"
