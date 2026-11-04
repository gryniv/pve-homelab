#!/bin/bash
# Removes PVE Homelab from the host, the kiosk's browser profiles included. Settings in /etc/pve-homelab
# stay (delete them by hand if you want).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }

for u in $(systemctl list-units --all --plain --no-legend 'pve-homelab-kiosk@*' | awk '{print $1}'); do
  systemctl disable --now "$u" || true
done
systemctl disable --now pve-homelab.service pve-homelab-update.timer 2>/dev/null || true
rm -rf /etc/systemd/system/pve-homelab-update.service /etc/systemd/system/pve-homelab-update.timer
rm -rf /etc/systemd/system/pve-homelab.service /etc/systemd/system/pve-homelab-kiosk@.service /etc/systemd/system/pve-homelab-kiosk@*.service.d
rm -f /etc/modules-load.d/pve-homelab.conf /etc/chromium/policies/managed/pve-homelab.json
rm -rf /opt/pve-homelab /opt/pve-homelab.prev /opt/pve-homelab.new /opt/pve-homelab.failed /var/cache/pve-homelab /var/log/pve-homelab
# The kiosk's browser profiles hold the cookies and saved logins of the services opened in it.
rm -rf /var/lib/pve-homelab/chromium /var/lib/pve-homelab/ext
systemctl daemon-reload
chvt 1 || true
echo "PVE Homelab removed. Packages (cage, chromium, ddcutil) and the pvehomelab user are left in place."
