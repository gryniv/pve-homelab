#!/bin/bash
# PVE Homelab installer for a Proxmox VE host. Run as root from the repository:
#
#   ./install.sh               install or update
#   ./install.sh --no-kiosk    backend only (no menu on the local screens)
#   ./install.sh --city Lviv --lang en    hints for the first-run config
#
# Safe to re-run: /etc/pve-homelab/config.yaml and per-user settings are never overwritten.
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

# Up to 0.3 this project was called "PVE Seat" (pve-seat units, /etc/pve-seat, user pveseat).
# Move its settings over once and remove the old units, files and kiosk user.
if [ -d /etc/pve-seat ] && [ ! -e /etc/pve-homelab ]; then
  echo "==> Migrating from PVE Seat"
  for u in $(systemctl list-units --all --plain --no-legend 'pve-seat-kiosk@*' | awk '{print $1}'); do
    systemctl disable --now "$u" >/dev/null 2>&1 || true
  done
  systemctl disable --now pve-seat-update.timer >/dev/null 2>&1 || true
  # the old backend is stopped last: this very script may be running from its update unit
  systemctl disable --now pve-seat.service >/dev/null 2>&1 || true
  cp -a /etc/pve-seat /etc/pve-homelab
  mv /etc/pve-seat /etc/pve-seat.migrated
  [ -d /var/log/pve-seat ] && mv /var/log/pve-seat /var/log/pve-homelab
  rm -rf /etc/systemd/system/pve-seat.service /etc/systemd/system/pve-seat-kiosk@.service \
         /etc/systemd/system/pve-seat-kiosk@*.service.d /etc/systemd/system/pve-seat-update.service \
         /etc/systemd/system/pve-seat-update.timer /opt/pve-seat /var/cache/pve-seat \
         /etc/modules-load.d/pve-seat.conf /etc/chromium/policies/managed/pve-seat.json
  if id pveseat >/dev/null 2>&1; then
    pkill -u pveseat 2>/dev/null || true; sleep 1
    userdel -r pveseat >/dev/null 2>&1 || true
  fi
  systemctl daemon-reload
  echo "    settings moved to /etc/pve-homelab (the old folder is kept as /etc/pve-seat.migrated)"
fi

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
PKGS="python3-aiohttp python3-yaml ddcutil"
[ "$KIOSK" = 1 ] && PKGS="$PKGS cage chromium fonts-noto-color-emoji"
# Fresh or long-idle hosts have stale package lists; refresh unless everything is already there.
if ! dpkg-query -W -f='${Status}\n' $PKGS 2>/dev/null | grep -qv '^install ok installed$' \
   && [ "$(dpkg-query -W -f='${Status}\n' $PKGS 2>/dev/null | wc -l)" -eq "$(echo $PKGS | wc -w)" ]; then
  echo "    already installed"
else
  apt-get update -qq
  apt-get install -y --no-install-recommends $PKGS >/dev/null
fi

echo "==> Kiosk user"
if ! id pvehomelab >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pve-homelab --shell /usr/sbin/nologin pvehomelab
fi
usermod -aG video,render,input pvehomelab

echo "==> Program files -> /opt/pve-homelab"
install -d /etc/pve-homelab/users /var/cache/pve-homelab
# The new version is assembled next to the running one and swapped in with two renames; the old
# one stays as /opt/pve-homelab.prev so the updater can put it back if the new one doesn't start.
NEW=/opt/pve-homelab.new
rm -rf "$NEW"
install -d "$NEW"
cp -r backend web kiosk "$NEW"/
[ -f VERSION ] && cp VERSION "$NEW"/
# What is installed and where it came from, for the updater (see backend/pvehomelab/update.py).
COMMIT="${PVEHOMELAB_COMMIT:-$(git rev-parse HEAD 2>/dev/null || true)}"
REPO="${PVEHOMELAB_REPO:-$(git remote get-url origin 2>/dev/null || true)}"
echo "$COMMIT" > "$NEW"/COMMIT
[ -n "$REPO" ] && echo "$REPO" > "$NEW"/REPO
chown -R root:root "$NEW"
chmod -R u=rwX,go=rX "$NEW"
chmod 755 "$NEW"/kiosk/kiosk.sh
find "$NEW" -name __pycache__ -prune -exec rm -rf {} +
if [ -d /opt/pve-homelab ]; then
  rm -rf /opt/pve-homelab.prev
  mv /opt/pve-homelab /opt/pve-homelab.prev
fi
mv "$NEW" /opt/pve-homelab

echo "==> DDC (monitor input switching)"
echo i2c-dev > /etc/modules-load.d/pve-homelab.conf
modprobe i2c-dev || true

if [ ! -f /etc/pve-homelab/config.yaml ]; then
  echo "==> First run: detecting GPUs, monitors and Caddy"
  (cd /opt/pve-homelab/backend && python3 -m pvehomelab.setup --write /etc/pve-homelab/config.yaml "${SETUP_ARGS[@]}")
fi
chmod 644 /etc/pve-homelab/config.yaml

if [ "$KIOSK" = 1 ]; then
  echo "==> Chromium policy (system DNS, no sign-in, no translate)"
  install -d /etc/chromium/policies/managed
  cp kiosk/chromium-policy.json /etc/chromium/policies/managed/pve-homelab.json
fi

echo "==> Services"
cp systemd/pve-homelab.service systemd/pve-homelab-kiosk@.service systemd/pve-homelab-update.service systemd/pve-homelab-update.timer /etc/systemd/system/
SEATS=$(python3 -c "
import yaml
c = yaml.safe_load(open('/etc/pve-homelab/config.yaml')) or {}
for sid, s in (c.get('seats') or {}).items():
    if s.get('kiosk'): print(sid, s.get('tty', 7))
")
systemctl daemon-reload
systemctl enable --now pve-homelab.service >/dev/null
systemctl enable --now pve-homelab-update.timer >/dev/null 2>&1
# An update installed from the menu runs inside pve-homelab-update-now; restarting the backend
# must not kill that run, so the restart happens without waiting for it.
systemctl restart --no-block pve-homelab.service

if [ "$KIOSK" = 1 ]; then
  while read -r sid tty; do
    [ -n "$sid" ] || continue
    d=/etc/systemd/system/pve-homelab-kiosk@$sid.service.d
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
    systemctl enable pve-homelab-kiosk@"$sid".service >/dev/null 2>&1
    systemctl restart pve-homelab-kiosk@"$sid".service
    echo "    menu on seat '$sid' (tty$tty)"
  done <<< "$SEATS"
  [ -n "$(echo "$SEATS" | tr -d '[:space:]')" ] || echo "    no seats in /etc/pve-homelab/config.yaml: no GPU with a monitor was found"
fi

echo
echo "Done. Text console: Ctrl+Alt+F1, menu: Ctrl+Alt+F7."
echo "Config: /etc/pve-homelab/config.yaml   Logs: journalctl -u pve-homelab -u 'pve-homelab-kiosk@*' -f"
