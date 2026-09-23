#!/bin/sh
# PVE Seat demo for Linux / macOS: ./demo.sh
# First run creates .demo/venv and installs aiohttp + PyYAML, then opens the browser.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Python 3.10+ is required"; exit 1; }
if [ ! -x .demo/venv/bin/python ]; then
  echo "Preparing the demo environment in .demo/venv ..."
  "$PY" -m venv .demo/venv
  .demo/venv/bin/python -m pip install -q -r requirements-demo.txt
fi
echo "PVE Seat demo: http://127.0.0.1:8900  (any password, Ctrl+C to stop)"
exec .demo/venv/bin/python demo.py "$@"
