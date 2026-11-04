"""Every host setting the menu can change, described once.

A setting has a dotted path into config (web.sign_in), a kind, its limits and a group; whether the
backend (or the kiosk) must restart for it to take effect. From these descriptions come the form in
Settings → System, the checks on the server and the test that nothing in config.DEFAULTS is left out.

What the menu changes goes to /etc/pve-homelab/settings.yaml, which wins over config.yaml; the
hand-written config.yaml (and its comments) is never touched. Taking a setting back out of
settings.yaml returns it to the file's value, or to the default.
"""

import copy
import ipaddress
import os
import re

import yaml

from . import config

FILE = "settings.yaml"

GROUPS = ("general", "access", "launch", "services", "weather", "alerts", "wol", "updates", "components")


class S:
    """kind: bool | int | choice | str | list (of `item`) | rows (list of dicts with `fields`) |
    map (name -> dict with `fields`)."""

    def __init__(self, path, kind, group, *, choices=(), lo=None, hi=None, item="word", fields=(),
                 restart=None, maxlen=200, pattern=None, null=False):
        self.path, self.kind, self.group = path, kind, group
        self.choices, self.lo, self.hi, self.item = tuple(choices), lo, hi, item
        self.fields, self.restart, self.maxlen = tuple(fields), restart, maxlen
        self.pattern = re.compile(pattern) if pattern else None
        self.null = null

    def describe(self):
        d = {"path": self.path, "kind": self.kind, "group": self.group, "restart": self.restart}
        if self.choices:
            d["choices"] = list(self.choices)
        if self.lo is not None:
            d["min"] = self.lo
        if self.hi is not None:
            d["max"] = self.hi
        if self.kind == "list":
            d["item"] = self.item
        if self.fields:
            d["fields"] = [{"key": k, "kind": kind, "required": req} for k, kind, req in self.fields]
        return d


ITEM = {
    "word": re.compile(r"^[\w.:@*-]{1,120}$"),
    "host": re.compile(r"^[\w.*-]{1,253}$"),
    "userid": re.compile(r"^[\w.-]{1,64}@[\w.-]{1,64}$"),
    "guest": re.compile(r"^(ct|vm)?\d{2,9}(-[\w-]{1,40})?(:\d{1,5})?$|^node$"),
}
MAC = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
URL = re.compile(r"^https?://[^\s\"'<>]{1,500}$")

# Services and links: name, icon, description (and the address of a link).
SVC_FIELDS = (("name", "str", False), ("icon", "str", False), ("desc", "str", False))

REGISTRY = [
    # who sees what, from where
    S("web.enabled", "bool", "access"),
    S("web.allow_from", "list", "access", item="net"),
    S("web.sign_in", "choice", "access", choices=("minimal", "users", "full")),
    S("allowed_hosts", "list", "access", item="host"),
    S("listen", "str", "access", pattern=r"^(\[[0-9a-fA-F:]+\]|[0-9.]+|localhost)?:\d{2,5}$", restart="all"),
    S("users.hide", "list", "access", item="userid"),
    # the menu itself
    S("node", "str", "general", pattern=r"^[A-Za-z0-9-]{0,63}$"),
    S("language", "choice", "general", choices=("uk", "en")),
    S("lock_after_min", "int", "general", lo=0, hi=1440),
    S("saver.after_min", "int", "general", lo=0, hi=1440),
    S("designer", "bool", "general"),
    S("kiosk.debug_port", "int", "general", lo=0, hi=65535, restart="kiosk"),
    # systems and how they start
    S("systems_tag", "str", "launch", pattern=r"^[a-z0-9_-]{1,32}$"),
    S("systems_extra", "list", "launch", item="vmid"),
    S("launch.assign_gpu", "bool", "launch"),
    S("launch.allow_igpu", "bool", "launch"),
    S("launch.return_to_menu", "bool", "launch"),
    S("launch.follow_start", "choice", "launch", choices=("boot", "always", "never")),
    S("input.mode", "choice", "launch", choices=("evdev", "off")),
    S("input.hotkey", "choice", "launch", choices=("ctrl-ctrl", "alt-alt", "shift-shift", "meta-meta", "scrolllock", "ctrl-scrolllock")),
    S("input.gamepads", "choice", "launch", choices=("usb", "off")),
    S("input.devices", "list", "launch", item="word"),
    # web services
    S("caddy.ct", "int", "services", lo=100, hi=999999999, null=True),
    S("caddy.admin", "str", "services", pattern=URL.pattern),
    S("caddy.prefer_suffix", "str", "services", pattern=r"^[\w.-]{0,100}$"),
    S("caddy.hide", "list", "services", item="word"),
    S("discovery.ports", "bool", "services"),
    S("discovery.vms", "bool", "services"),
    S("discovery.notes", "bool", "services"),
    S("discovery.ignore", "list", "services", item="guest"),
    S("services", "map", "services", fields=SVC_FIELDS),
    S("links", "rows", "services", fields=(("name", "str", True), ("url", "url", True), ("icon", "str", False), ("desc", "str", False))),
    # weather for those who haven't picked their own
    S("weather.city", "str", "weather", maxlen=100),
    S("weather.units", "choice", "weather", choices=("c", "f")),
    # the bell
    S("alerts.storage_pct", "int", "alerts", lo=50, hi=100),
    S("alerts.temp_c", "int", "alerts", lo=40, hi=120),
    S("alerts.backup_days", "int", "alerts", lo=1, hi=365),
    # wake-on-LAN
    S("wol", "rows", "wol", fields=(("name", "str", True), ("mac", "mac", True), ("broadcast", "ip", False), ("port", "port", False))),
    # updates of the menu
    S("update.auto", "bool", "updates"),
    S("update.channel", "choice", "updates", choices=("release", "main")),
    S("update.check_hours", "int", "updates", lo=1, hi=168, restart="backend"),
    S("update.repo", "str", "updates", pattern=r"^([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*|https://github\.com/[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)?$"),
    S("feedback.enabled", "bool", "components"),
    S("feedback.repo", "str", "updates", pattern=r"^([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)?$"),
]
FEATURES = ("alerts", "node_updates", "app_updates", "weather", "consoles", "guest_actions", "guest_settings", "host_power", "wol", "my_designs", "my_widgets")
REGISTRY += [S(f"features.{f}", "bool", "components") for f in FEATURES]
BY_PATH = {s.path: s for s in REGISTRY}

# In config.DEFAULTS but not in the form, and why (the test keeps this list honest):
NOT_IN_MENU = {
    "seats": "found by setup on install; Settings → System shows them",
    "monitors": "found by setup; DDC input codes are edited with the monitor test",
    "update.branch": "for the main channel only, by hand",
}


def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None, False
        d = d[k]
    return d, True


def _set(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


def _drop(d, path):
    keys = path.split(".")
    stack = [d]
    for k in keys[:-1]:
        if not isinstance(stack[-1].get(k), dict):
            return
        stack.append(stack[-1][k])
    stack[-1].pop(keys[-1], None)
    for i in range(len(keys) - 1, 0, -1):     # no empty dicts left behind
        if not stack[i]:
            stack[i - 1].pop(keys[i - 1], None)


class Invalid(ValueError):
    pass


def _item(kind, v):
    if kind == "vmid":
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isdigit() or not 100 <= int(v) <= 999999999:
            raise Invalid("vmid")
        return int(v)
    if kind == "net":
        try:
            return str(ipaddress.ip_network(str(v).strip(), strict=False)) if "/" in str(v) else str(ipaddress.ip_address(str(v).strip()))
        except ValueError:
            raise Invalid("address or network")
    v = str(v).strip()
    if not ITEM.get(kind, ITEM["word"]).match(v):
        raise Invalid(kind)
    return v


def _field(kind, v, maxlen=200):
    if kind == "mac":
        v = str(v).strip()
        if not MAC.match(v):
            raise Invalid("mac")
        return v.lower().replace("-", ":")
    if kind == "url":
        v = str(v).strip()
        if not URL.match(v):
            raise Invalid("url")
        return v
    if kind == "ip":
        try:
            return str(ipaddress.ip_address(str(v).strip()))
        except ValueError:
            raise Invalid("ip")
    if kind == "port":
        if isinstance(v, bool) or not str(v).isdigit() or not 1 <= int(v) <= 65535:
            raise Invalid("port")
        return int(v)
    v = str(v)
    if len(v) > maxlen or any(c in v for c in "\r\n\0"):
        raise Invalid("text")
    return v


def check(path, value):
    """The value as it will be kept, or Invalid."""
    s = BY_PATH.get(path)
    if not s:
        raise Invalid("unknown setting")
    if value is None and s.null:
        return None
    if s.kind == "bool":
        if not isinstance(value, bool):
            raise Invalid("yes or no")
        return value
    if s.kind == "int":
        if isinstance(value, bool):
            raise Invalid("number")
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise Invalid("number")
        if (s.lo is not None and n < s.lo) or (s.hi is not None and n > s.hi):
            raise Invalid(f"{s.lo}…{s.hi}")
        return n
    if s.kind == "choice":
        if value not in s.choices:
            raise Invalid("one of " + ", ".join(s.choices))
        return value
    if s.kind == "str":
        if not isinstance(value, str) or len(value) > s.maxlen or any(c in value for c in "\r\n\0"):
            raise Invalid("text")
        if s.pattern and not s.pattern.match(value):
            raise Invalid("format")
        return value
    if s.kind == "list":
        if isinstance(value, str):
            value = [x for x in re.split(r"[\s,]+", value) if x]
        if not isinstance(value, list) or len(value) > 200:
            raise Invalid("list")
        return [_item(s.item, v) for v in value]
    if s.kind in ("rows", "map"):
        rows = value.items() if s.kind == "map" and isinstance(value, dict) else enumerate(value) if s.kind == "rows" and isinstance(value, list) else None
        if rows is None or len(value) > 200:
            raise Invalid("list")
        out = {} if s.kind == "map" else []
        for key, row in rows:
            if not isinstance(row, dict):
                raise Invalid("row")
            item = {}
            for f, kind, required in s.fields:
                v = row.get(f)
                if v in (None, ""):
                    if required:
                        raise Invalid(f"{f} is needed")
                    continue
                item[f] = _field(kind, v)
            if s.kind == "map":
                key = _item("word", key)
                out[key] = item
            else:
                out.append(item)
        return out
    raise Invalid("kind")


# ---------------------------------------------------------------- the file the menu writes

def path():
    return os.path.join(config.STATE_DIR, FILE)


def load_overlay():
    """settings.yaml, with anything that no longer checks out left out (a hand edit, an older
    version): a bad line costs that setting, never the menu."""
    try:
        with open(path(), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    out = {}
    if not isinstance(raw, dict):
        return out
    for s in REGISTRY:
        v, there = _get(raw, s.path)
        if there:
            try:
                _set(out, s.path, check(s.path, v))
            except Invalid:
                pass
    return out


def save_overlay(data):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Changed in the menu (Settings → System); wins over config.yaml. Remove a line to go back to it.\n")
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    os.replace(tmp, path())


def change(sets=None, resets=()):
    """Set {path: value}, and take `resets` back to config.yaml. Returns (overlay, {path: error});
    nothing is written when any value is wrong."""
    over = load_overlay()
    errors = {}
    for p in resets or ():
        if p not in BY_PATH:
            errors[p] = "unknown setting"
        else:
            _drop(over, p)
    for p, v in (sets or {}).items():
        if p not in BY_PATH:
            errors[p] = "unknown setting"
            continue
        try:
            _set(over, p, check(p, v))
        except Invalid as e:
            errors[p] = str(e)
    if not errors:
        save_overlay(over)
    return over, errors


def describe(cfg_file, over):
    """The form: every setting with its value, where it comes from and what the file says."""
    base = config._merge(config.DEFAULTS, cfg_file)
    eff = config._merge(base, over)
    out = []
    for s in REGISTRY:
        v, _ = _get(eff, s.path)
        _, in_over = _get(over, s.path)
        _, in_file = _get(cfg_file, s.path)
        fv, _ = _get(base, s.path)
        out.append({**s.describe(), "value": copy.deepcopy(v), "file_value": copy.deepcopy(fv),
                    "source": "menu" if in_over else "file" if in_file else "default"})
    return out


def restart_needed(paths):
    """What has to restart for these settings: "backend", "kiosk" or "all"."""
    want = {BY_PATH[p].restart for p in paths if p in BY_PATH and BY_PATH[p].restart}
    if "all" in want or {"backend", "kiosk"} <= want:
        return "all"
    return next(iter(want), None)
