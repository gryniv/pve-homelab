#!/bin/bash
# Removes PVE Homelab from the host, the kiosk's browser profiles included. Settings in /etc/pve-homelab
# stay, unless --purge: then a copy of them goes to /root first, and the settings and the
# pvehomelab user go too.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

if [ "$PURGE" = 1 ] && [ -d /opt/pve-homelab/backend ]; then
  COPY="/root/pve-homelab-settings-$(date +%Y%m%d-%H%M%S).tar.gz"
  (cd /opt/pve-homelab/backend && python3 -m pvehomelab.backup export -o "$COPY") >/dev/null
  echo "A copy of the settings: $COPY"
fi

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
if [ "$PURGE" = 1 ]; then
  rm -rf /etc/pve-homelab /var/lib/pve-homelab
  userdel pvehomelab 2>/dev/null || true
  echo "PVE Homelab removed with its settings. Packages (cage, chromium, ddcutil) are left in place."
else
  echo "PVE Homelab removed. Settings in /etc/pve-homelab, packages (cage, chromium, ddcutil) and the pvehomelab user are left in place."
fi
