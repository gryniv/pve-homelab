import copy
import os
import socket

import yaml

CONFIG_PATH = os.environ.get("PVESEAT_CONFIG", "/etc/pve-seat/config.yaml")
STATE_DIR = os.environ.get("PVESEAT_STATE", "/etc/pve-seat")
WEB_DIR = os.environ.get("PVESEAT_WEB", "/opt/pve-seat/web")
CACHE_DIR = os.environ.get("PVESEAT_CACHE", "/var/cache/pve-seat")

DEFAULTS = {
    "listen": "127.0.0.1:8900",
    "node": "",
    "systems_tag": "seat",
    "systems_extra": [],
    "seats": {},
    "monitors": {},
    "launch": {"assign_gpu": True, "allow_igpu": False, "return_to_menu": True},
    "caddy": {"ct": None, "admin": "http://localhost:2019", "prefer_suffix": "", "hide": []},
    "services": {},
    "weather": {"city": "Київ", "units": "c"},
    "users": {"hide": []},
    "saver": {"after_min": 5},
    "lock_after_min": 15,
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    cfg["node"] = cfg["node"] or socket.gethostname().split(".")[0]
    # YAML gives hex input codes as ints already; PCI keys stay strings.
    for mon in cfg["monitors"].values():
        mon["inputs"] = {str(k): int(v) for k, v in (mon.get("inputs") or {}).items()}
    return cfg
