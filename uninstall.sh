#!/bin/bash
# Прибирає PVE Seat з хоста. Налаштування в /etc/pve-seat лишаються (видали вручну, якщо треба).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Потрібен root"; exit 1; }

for u in $(systemctl list-units --all --plain --no-legend 'pve-seat-kiosk@*' | awk '{print $1}'); do
  systemctl disable --now "$u" || true
done
systemctl disable --now pve-seat.service pve-seat-update.timer 2>/dev/null || true
rm -rf /etc/systemd/system/pve-seat-update.service /etc/systemd/system/pve-seat-update.timer
rm -rf /etc/systemd/system/pve-seat.service /etc/systemd/system/pve-seat-kiosk@.service /etc/systemd/system/pve-seat-kiosk@*.service.d
rm -f /etc/modules-load.d/pve-seat.conf
rm -rf /opt/pve-seat /var/cache/pve-seat /var/log/pve-seat
systemctl daemon-reload
chvt 1 || true
echo "PVE Seat прибрано. Пакети (cage, chromium, ddcutil) і користувач pveseat лишились."
