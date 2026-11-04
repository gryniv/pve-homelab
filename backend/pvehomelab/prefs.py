"""Per-user settings: /etc/pve-homelab/users/<userid>.yaml"""

import copy
import os
import re

import yaml

from .config import STATE_DIR

DEFAULT = {
    "lang": "",                   # empty = the screen's default language
    "skin": "dusk",
    "background": "scene",        # scene | still | mountains | sea | dunes | city | hills | night | gradient | aurora | dots | grid | solid | black
    "clock": "digital",           # designs/clocks/<id>.js
    "fonts": {"ui": "", "display": ""},     # designs/fonts/<id>.css; empty = the theme's font
    "weather_react": True,
    "sky_by_time": True,
    "layout": {"login": ["weather", "host"], "side": ["host", "gpus"]},
    "widget_opts": {},            # {<widget id>: {<option>: value}}, see "options" in web/widgets/<id>/widget.js
    "theme_opts": {},             # {<theme id>: {<option>: value}}, see "@option" in a theme's header
    # what each design was last worn with, so coming back to it brings that back:
    # {<theme id>: {"background": id, "clock": id, "fonts": {"ui": id, "display": id}}}
    "looks": {},
    "weather": {"city": "", "units": ""},   # empty = as in config.yaml
    "launch": {"gpu": "auto", "ask": True, "pass_input": True},
    "saver": {"fx": True, "clock": True},
    "top": {"pve_updates": True},  # the top bar's Proxmox updates button (shown only to those who may update)
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
            # the chosen theme's own settings, so the sign-in screen looks the way this person set it
            "theme_opts": {pr["skin"]: pr["theme_opts"].get(pr["skin"], {})},
            # options of the sign-in screen widgets only (the rest stays private)
            "widget_opts": {k: v for k, v in pr["widget_opts"].items() if k in pr["layout"].get("login", [])}}


# Sign-in screen of the whole host (not per user): /etc/pve-homelab/login.yaml, edited by admins.
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


MAX_STR = {"note": 4000}      # longer free text; any other string is capped at MAX_STR_DEFAULT
MAX_STR_DEFAULT = 300
MAX_LIST = 200


def _same_kind(default, v):
    """A stored value must have the default's type, or a later read of it fails for everyone
    (the sign-in screen shows every user's public settings)."""
    if isinstance(default, bool):
        return isinstance(v, bool)
    if isinstance(default, int):
        return isinstance(v, int) and not isinstance(v, bool)
    if isinstance(default, str):
        return isinstance(v, str)
    if isinstance(default, list):
        return isinstance(v, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in v)
    return True


_OPT = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")


def _theme_opts(v):
    """{theme: {option: value}} with nothing but short plain names in it (the sign-in screen reads it)."""
    if not isinstance(v, dict):
        return {}
    out = {}
    for theme, opts in list(v.items())[:MAX_LIST]:
        if isinstance(theme, str) and _OPT.match(theme) and isinstance(opts, dict):
            out[theme] = {k: val for k, val in list(opts.items())[:8]
                          if isinstance(k, str) and isinstance(val, str) and _OPT.match(k) and _OPT.match(val)}
    return out


_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")     # a design's id, as designs.py names them


def _looks(v):
    """{theme: {background, clock, fonts: {ui, display}}} with design ids only; an empty font is the theme's own."""
    if not isinstance(v, dict):
        return {}
    out = {}
    for theme, look in list(v.items())[:MAX_LIST]:
        if not (isinstance(theme, str) and _ID.match(theme) and isinstance(look, dict)):
            continue
        one = {k: look[k] for k in ("background", "clock") if isinstance(look.get(k), str) and _ID.match(look[k])}
        f = look.get("fonts")
        if isinstance(f, dict):
            one["fonts"] = {k: f[k] for k in ("ui", "display")
                            if isinstance(f.get(k), str) and (f[k] == "" or _ID.match(f[k]))}
        if one:
            out[theme] = one
    return out


def _merge(base, over):
    """Defaults overlaid with `over`: unknown keys are dropped, values of the wrong type keep
    the default, and strings and lists are capped."""
    out = copy.deepcopy(base)
    if not isinstance(over, dict):
        return out
    for k, v in over.items():
        if k not in base:
            continue
        d = base[k]
        if k == "theme_opts":
            out[k] = _theme_opts(v)
        elif k == "looks":
            out[k] = _looks(v)
        elif isinstance(d, dict):
            if not isinstance(v, dict):
                continue
            # an empty default dict is free-form (widget_opts): keep whatever is stored
            out[k] = copy.deepcopy(v) if not d else _merge(d, v)
        elif _same_kind(d, v):
            if isinstance(v, str):
                v = v[:MAX_STR.get(k, MAX_STR_DEFAULT)]
            elif isinstance(v, list):
                v = v[:MAX_LIST]
            out[k] = copy.deepcopy(v)
    return out


def load_defaults():
    return copy.deepcopy(DEFAULT)


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
