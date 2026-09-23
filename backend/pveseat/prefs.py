"""Per-user settings: /etc/pve-seat/users/<userid>.yaml"""

import copy
import os
import re

import yaml

from .config import STATE_DIR

DEFAULT = {
    "lang": "",                   # empty = the screen's default language
    "skin": "dusk",
    "background": "scene",        # scene | still | mountains | sea | dunes | city | hills | night | gradient | aurora | dots | grid | solid | black
    "weather_react": True,
    "sky_by_time": True,
    "layout": {"login": ["weather", "host"], "side": ["host", "gpus"]},
    "weather": {"city": "", "units": ""},   # порожньо = як у config.yaml
    "launch": {"gpu": "auto", "ask": True, "pass_input": True},
    "saver": {"fx": True, "clock": True},
    "hidden_services": [],
    "hidden_systems": [],
    # manual = the user's own order (drag on the dashboard or ↑↓ in settings), name, status = running first
    "sort": {"services": "manual", "systems": "manual"},
    "order": {"services": [], "systems": []},
    "avatar": 0,
    "show_on_login": True,
    "note": "",
}


def _path(user):
    safe = re.sub(r"[^A-Za-z0-9@._-]", "_", user)
    return os.path.join(STATE_DIR, "users", safe + ".yaml")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            continue
        out[k] = _merge(base[k], v) if isinstance(base[k], dict) and isinstance(v, dict) else v
    return out


def load(user):
    p = _path(user)
    data = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    return _merge(DEFAULT, data)


def save(user, data):
    merged = _merge(DEFAULT, data)
    p = _path(user)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, p)
    return merged
