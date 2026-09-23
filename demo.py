#!/usr/bin/env python3
"""Run the PVE Homelab menu on any computer, no Proxmox needed.

    pip install -r requirements-demo.txt
    python demo.py                 # opens http://127.0.0.1:8900 in your browser
    python demo.py --port 9000 --lang uk --no-browser

Everything is made up and kept in memory: VMs, containers, GPUs, web services, users
(ihor@pve, guest@pve with limited rights, root@pam) and host load. Any password works.
Settings you change are saved under .demo/ next to this file.
"""

import argparse
import locale
import os
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--lang", help="uk or en (default: from your system)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    # Paths must be set before pvehomelab is imported.
    os.environ["PVEHOMELAB_CONFIG"] = os.path.join(ROOT, "etc", "demo.yaml")
    os.environ["PVEHOMELAB_WEB"] = os.path.join(ROOT, "web")
    os.environ["PVEHOMELAB_STATE"] = os.path.join(ROOT, ".demo", "state")
    os.environ["PVEHOMELAB_CACHE"] = os.path.join(ROOT, ".demo", "cache")
    os.environ["PVEHOMELAB_INSTALL"] = ROOT
    sys.path.insert(0, os.path.join(ROOT, "backend"))

    try:
        import aiohttp  # noqa: F401
        import yaml  # noqa: F401
    except ImportError:
        sys.exit("Missing packages. Run:  pip install -r requirements-demo.txt")

    from pvehomelab import config, demo

    lang = a.lang or ("uk" if (locale.getlocale()[0] or "").lower().startswith(("uk", "ukrainian")) else "en")
    real_load = config.load

    def load():
        cfg = real_load()
        cfg["language"] = lang
        return cfg
    config.load = load

    url = f"http://{a.host}:{a.port}/?seat=igpu"
    print(f"PVE Homelab demo: {url}  (any password, Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    demo.run(a.host, a.port)


if __name__ == "__main__":
    main()
