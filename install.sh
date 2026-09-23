#!/bin/bash
# Встановлення PVE Seat на хост Proxmox. Запускати від root з папки проєкту:
#   ./install.sh            встановити або оновити
# Повторний запуск безпечний: config.yaml і налаштування користувачів не перезаписуються.
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" = 0 ] || { echo "Потрібен root"; exit 1; }
command -v pveversion >/dev/null || { echo "Це не хост Proxmox"; exit 1; }

echo "==> Пакети"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends cage chromium ddcutil python3-aiohttp python3-yaml \
  fonts-noto-color-emoji >/dev/null

echo "==> Користувач kiosk"
if ! id pveseat >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pve-seat --shell /usr/sbin/nologin pveseat
fi
usermod -aG video,render,input pveseat

echo "==> Файли програми -> /opt/pve-seat"
install -d /opt/pve-seat /etc/pve-seat/users /var/cache/pve-seat
rm -rf /opt/pve-seat/backend /opt/pve-seat/web /opt/pve-seat/kiosk
cp -r backend web kiosk /opt/pve-seat/
chown -R root:root /opt/pve-seat
chmod -R u=rwX,go=rX /opt/pve-seat
chmod 755 /opt/pve-seat/kiosk/kiosk.sh
find /opt/pve-seat -name __pycache__ -prune -exec rm -rf {} +
[ -f /etc/pve-seat/config.yaml ] || cp etc/config.yaml /etc/pve-seat/config.yaml
chmod 644 /etc/pve-seat/config.yaml

echo "==> Політика Chromium (системний DNS: *.hryniv.dev -> Caddy в LAN, а не зовнішня адреса)"
install -d /etc/chromium/policies/managed
cp kiosk/chromium-policy.json /etc/chromium/policies/managed/pve-seat.json

echo "==> DDC (перемикання входів монітора)"
echo i2c-dev > /etc/modules-load.d/pve-seat.conf
modprobe i2c-dev

echo "==> Служби"
cp systemd/pve-seat.service systemd/pve-seat-kiosk@.service /etc/systemd/system/
SEATS=$(python3 -c "
import yaml
c = yaml.safe_load(open('/etc/pve-seat/config.yaml'))
for sid, s in (c.get('seats') or {}).items():
    if s.get('kiosk'): print(sid, s.get('tty', 7))
")
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
systemctl enable --now pve-seat.service
systemctl restart pve-seat.service
while read -r sid tty; do
  [ -n "$sid" ] || continue
  systemctl enable pve-seat-kiosk@"$sid".service
  systemctl restart pve-seat-kiosk@"$sid".service
  echo "    меню на місці «$sid» (tty$tty)"
done <<< "$SEATS"

echo
echo "Готово. Консоль лишається на Ctrl+Alt+F1, меню на Ctrl+Alt+F7."
echo "Журнали: journalctl -u pve-seat -u 'pve-seat-kiosk@*' -f"
