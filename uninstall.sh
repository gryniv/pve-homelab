#!/bin/bash
# Removes PVE Homelab from the host. Settings in /etc/pve-homelab stay (delete them by hand if you want).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }

for u in $(systemctl list-units --all --plain --no-legend 'pve-homelab-kiosk@*' | awk '{print $1}'); do
  systemctl disable --now "$u" || true
done
systemctl disable --now pve-homelab.service pve-homelab-update.timer 2>/dev/null || true
rm -rf /etc/systemd/system/pve-homelab-update.service /etc/systemd/system/pve-homelab-update.timer
rm -rf /etc/systemd/system/pve-homelab.service /etc/systemd/system/pve-homelab-kiosk@.service /etc/systemd/system/pve-homelab-kiosk@*.service.d
rm -f /etc/modules-load.d/pve-homelab.conf /etc/chromium/policies/managed/pve-homelab.json
rm -rf /opt/pve-homelab /var/cache/pve-homelab /var/log/pve-homelab
systemctl daemon-reload
chvt 1 || true
echo "PVE Homelab removed. Packages (cage, chromium, ddcutil) and the pvehomelab user are left in place."
