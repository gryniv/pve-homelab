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
    "clock": "digital",           # web/clocks/<id>.js
    "fonts": {"ui": "", "display": ""},     # web/fonts/<id>.css; empty = the theme's font
    "weather_react": True,
    "sky_by_time": True,
    "layout": {"login": ["weather", "host"], "side": ["host", "gpus"]},
    "widget_opts": {},            # {<widget id>: {<option>: value}}, see "options" in web/widgets/<id>/widget.js
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


# What the sign-in screen may show about a user before they sign in.
def public(pr):
    return {"avatar": pr["avatar"], "skin": pr["skin"], "background": pr["background"], "clock": pr["clock"],
            "fonts": pr["fonts"], "login": pr["layout"].get("login", []), "lang": pr["lang"],
            # options of the sign-in screen widgets only (the rest stays private)
            "widget_opts": {k: v for k, v in pr["widget_opts"].items() if k in pr["layout"].get("login", [])}}


# Sign-in screen of the whole host (not per user): /etc/pve-seat/login.yaml, edited by admins.
LOGIN_DEFAULT = {
    "title": "",             # a line above the clock, e.g. "Home server"
    "other_user": True,      # the "someone else" tile for typing a user name
    "remember_last": True,   # preselect whoever signed in last on this seat
    "avatars": "large",      # large | small
    "date": True,
    "hostline": True,
}


def load_login():
    p = os.path.join(STATE_DIR, "login.yaml")
    data = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    return _merge(LOGIN_DEFAULT, data)


def save_login(data):
    merged = _merge(LOGIN_DEFAULT, data)
    p = os.path.join(STATE_DIR, "login.yaml")
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    os.replace(p + ".tmp", p)
    return merged


def _path(user):
    safe = re.sub(r"[^A-Za-z0-9@._-]", "_", user)
    return os.path.join(STATE_DIR, "users", safe + ".yaml")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            continue
        if isinstance(base[k], dict) and isinstance(v, dict):
            # an empty default dict is free-form (widget_opts): keep whatever is stored
            out[k] = copy.deepcopy(v) if not base[k] else _merge(base[k], v)
        else:
            out[k] = v
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
