"""Designs: how the menu looks, kept apart from the program.

    designs/themes/<id>.css         colours (CSS custom properties only)
    designs/backgrounds/<id>.css    the sign-in and dashboard background
    designs/clocks/<id>.js          a clock design (an ES module)
    designs/fonts/<id>.css          a font
    designs/widgets/<id>.css        how widget <id> looks (its logic stays in web/widgets/<id>/)

Two places are read: the designs that ship with PVE Homelab (config.DESIGNS_DIR, replaced by
updates) and your own (config.USER_DESIGNS_DIR, /etc/pve-homelab/designs, kept by updates). A file
of yours with the same id as a built-in one replaces it. Each file describes itself in its first
comment: @name.en Dusk / @name.uk Сутінки / @desc.en … / @group … / @order 10.
"""

import os
import re

from . import config

KINDS = {"themes": "css", "backgrounds": "css", "clocks": "js", "fonts": "css", "widgets": "css"}
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_BYTES = 512 * 1024  # a design is a stylesheet or a small module, not an asset bundle


def roots():
    """(folder, source) to look in, yours first."""
    return [(config.USER_DESIGNS_DIR, "user"), (config.DESIGNS_DIR, "builtin")]


def path_of(kind, did):
    """The file serving design `did` of `kind` (yours before the built-in one), or None."""
    if kind not in KINDS or not ID.match(did or ""):
        return None
    for root, _src in roots():
        p = os.path.join(root, kind, f"{did}.{KINDS[kind]}")
        if os.path.isfile(p):
            return p
    return None


def meta_of(path, did):
    """The header comment's @keys: name/desc per language, anything else as is."""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4000)
    except OSError:
        head = ""
    m = re.search(r"/\*(.*?)\*/", head, re.S)
    meta = {"id": did, "name": {}, "desc": {}}
    for key, code, val in re.findall(r"@(\w+)(?:\.(\w+))?[ \t]+([^\n*]+)", m.group(1) if m else ""):
        if key in ("name", "desc"):
            meta[key][code or "en"] = val.strip()
        else:
            meta[key] = val.strip()
    meta["name"] = meta["name"] or {"en": did}
    return meta


def catalog(kind):
    """Every design of `kind`, built-in and yours merged by id (yours wins), in display order."""
    found = {}
    for root, src in reversed(roots()):  # built-in first, then yours on top
        folder = os.path.join(root, kind)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            did, ext = os.path.splitext(name)
            if ext != "." + KINDS[kind] or not ID.match(did):
                continue
            meta = meta_of(os.path.join(folder, name), did)
            meta["source"] = src
            if src == "user" and did in found:
                meta["replaces"] = "builtin"
            found[did] = meta
    return sorted(found.values(), key=lambda m: (int(m.get("order", 50)) if str(m.get("order", "")).isdigit() else 50, m["id"]))
