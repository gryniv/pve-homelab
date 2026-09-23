#!/bin/bash
# Pull the latest version and reinstall. Settings in /etc/pve-homelab are kept.
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only
exec ./install.sh "$@"
