import copy
import os
import socket
import sys

import yaml

CONFIG_PATH = os.environ.get("PVEHOMELAB_CONFIG", "/etc/pve-homelab/config.yaml")
STATE_DIR = os.environ.get("PVEHOMELAB_STATE", "/etc/pve-homelab")
WEB_DIR = os.environ.get("PVEHOMELAB_WEB", "/opt/pve-homelab/web")
# Looks live apart from the program: the ones that ship with it (replaced by updates) and your own
# (kept by updates; a design here with the same id as a built-in one wins).
DESIGNS_DIR = os.environ.get("PVEHOMELAB_DESIGNS", "/opt/pve-homelab/designs")
USER_DESIGNS_DIR = os.environ.get("PVEHOMELAB_USER_DESIGNS", os.path.join(STATE_DIR, "designs"))
# Your own widgets (logic: <id>/widget.js), kept by updates; their look is a design (widgets/<id>.css).
USER_WIDGETS_DIR = os.environ.get("PVEHOMELAB_USER_WIDGETS", os.path.join(STATE_DIR, "widgets"))
CACHE_DIR = os.environ.get("PVEHOMELAB_CACHE", "/var/cache/pve-homelab")

DEFAULTS = {
    "listen": "127.0.0.1:8900",
    "allowed_hosts": [],       # extra Host names the menu answers to; "*" turns the check off
    # The menu in a browser elsewhere, through a reverse proxy (e.g. Caddy on home.example.com).
    # Only loopback and these addresses or networks may talk to the backend; whatever does not
    # come from loopback is the "web" seat, which never touches a monitor or a GPU.
    "web": {"enabled": True, "allow_from": [], "sign_in": "minimal"},
    "node": "",
    "language": "en",
    "systems_tag": "seat",
    "systems_extra": [],
    "links": [],
    "wol": [],                 # [{name, mac, broadcast?, port?}]: machines the menu can wake up
    "kiosk": {"debug_port": 0},
    "update": {"repo": "", "channel": "release", "branch": "main", "auto": False, "check_hours": 6},
    "seats": {},
    "monitors": {},
    "launch": {"assign_gpu": True, "allow_igpu": False, "return_to_menu": True, "follow_start": "boot"},
    "caddy": {"ct": None, "admin": "http://localhost:2019", "prefer_suffix": "", "hide": []},
    "discovery": {"ports": True, "vms": True, "notes": True, "ignore": []},
    "services": {},
    "weather": {"city": "Kyiv", "units": "c"},
    "users": {"hide": []},
    "saver": {"after_min": 5},
    "lock_after_min": 15,
    "designer": False,         # live reload of designs (the demo has it on): for working on designs on a host
    "alerts": {"storage_pct": 90, "temp_c": 85, "backup_days": 7},
    # Settings → About → Write to the author: a GitHub issue in `repo` (default: where updates come from)
    "feedback": {"enabled": True, "repo": ""},
    # Parts of the menu that can be switched off for the whole host (Settings → System → Components):
    # what is off leaves the menu and its API answers 404.
    "features": {"alerts": True, "node_updates": True, "app_updates": True, "weather": True, "consoles": True, "guest_actions": True, "guest_settings": True, "host_power": True, "wol": True, "my_designs": True, "my_widgets": True},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_file():
    """config.yaml as written by hand (or by setup), without defaults."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    return {}


def load():
    """DEFAULTS, then config.yaml, then what was changed in the menu (settings.yaml)."""
    from . import settings
    cfg = _merge(_merge(DEFAULTS, load_file()), settings.load_overlay())
    cfg["node"] = cfg["node"] or socket.gethostname().split(".")[0]
    # YAML gives hex input codes as ints already; PCI keys stay strings.
    for mon in cfg["monitors"].values():
        mon["inputs"] = {str(k): int(v) for k, v in (mon.get("inputs") or {}).items()}
    return cfg


LOOPBACK = ("127.0.0.1", "::1", "localhost", "0.0.0.0", "::", "")


def menu_host(cfg):
    """host:port where the menu answers on this machine (the kiosk, the updater's health check,
    Proxmox's notification webhook). `listen` on every address means loopback too."""
    host, port = cfg["listen"].rsplit(":", 1)
    host = host.strip("[]")
    if host in ("0.0.0.0", "", "localhost"):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def menu_url(cfg, seat=None):
    return f"http://{menu_host(cfg)}/" + (f"?seat={seat}" if seat else "")


def listens_on_loopback(cfg):
    host = cfg["listen"].rsplit(":", 1)[0].strip("[]")
    return host in LOOPBACK or host.startswith("127.")


def _cli(argv):
    """For the shell scripts, so they read config.yaml the way the backend does:
         python3 -m pvehomelab.config kiosk <seat>   ->  <gpu> <debug port> <menu url>
         python3 -m pvehomelab.config seats          ->  <seat> <tty>, one per kiosk seat
         python3 -m pvehomelab.config url            ->  the menu's own address"""
    cfg = load()
    if argv[:1] == ["kiosk"] and len(argv) == 2:
        seat = cfg["seats"][argv[1]]
        if not listens_on_loopback(cfg):
            print(f"listen: {cfg['listen']} leaves out loopback: the kiosk would count as a browser elsewhere; "
                  "use 0.0.0.0:<port> or 127.0.0.1:<port>", file=sys.stderr)
        print(seat["gpu"], int((cfg.get("kiosk") or {}).get("debug_port") or 0), menu_url(cfg, argv[1]))
    elif argv == ["seats"]:
        for sid, s in cfg["seats"].items():
            if s.get("kiosk"):
                print(sid, s.get("tty", 7))
    elif argv == ["url"]:
        print(menu_url(cfg))
    else:
        print(_cli.__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
