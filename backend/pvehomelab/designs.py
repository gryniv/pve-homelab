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

import io
import os
import re
import zipfile

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


# ---------------- installing your own (from the menu) ----------------
MAX_FILES = 50
MAX_TOTAL = 8 * 1024 * 1024
ALIASES = {"theme": "themes", "background": "backgrounds", "clock": "clocks", "font": "fonts", "widget": "widgets"}


class DesignError(ValueError):
    """A file that can't be installed as a design; the message says why."""


def kind_of(name, text, folder=None):
    """Which kind a design file is: the folder it came in (themes/…), its @kind, or what it paints."""
    if folder:
        k = ALIASES.get(folder, folder)
        if k in KINDS:
            return k
    m = re.search(r"/\*(.*?)\*/", text[:4000], re.S)
    declared = re.search(r"@kind[ \t]+(\w+)", m.group(1)) if m else None
    if declared:
        k = declared.group(1).lower()
        k = ALIASES.get(k, k)
        if k not in KINDS:
            raise DesignError(f"{name}: unknown @kind {declared.group(1)}")
        return k
    if name.endswith(".js"):
        return "clocks"
    if ".bgx" in text:
        return "backgrounds"
    if re.search(r"@family\b", text[:4000]):
        return "fonts"
    if "[data-skin" in text:
        return "themes"
    if ".w[data-w" in text:
        return "widgets"
    raise DesignError(f"{name}: can't tell what kind of design this is; add @kind to its first comment")


def _check(name, data, folder=None):
    """(kind, id, text) of one design file, or DesignError."""
    base = os.path.basename(name)
    did, ext = os.path.splitext(base)
    if not ID.match(did):
        raise DesignError(f"{base}: the name must be lower-case letters, digits, - or _")
    if ext not in (".css", ".js"):
        raise DesignError(f"{base}: only .css and .js designs (or a .zip of them)")
    if len(data) > MAX_BYTES:
        raise DesignError(f"{base}: larger than {MAX_BYTES // 1024} KB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DesignError(f"{base}: not UTF-8 text") from None
    kind = kind_of(base, text, folder)
    if ext != "." + KINDS[kind]:
        raise DesignError(f"{base}: a {kind[:-1]} design is a .{KINDS[kind]} file")
    return kind, did, text


def unpack(files):
    """[(name, bytes)] as uploaded -> [(kind, id, text)]; a .zip may hold many, in kind folders
    (themes/dusk2.css) or loose with @kind in each file's first comment."""
    out, total = [], 0
    for name, data in files:
        total += len(data)
        if total > MAX_TOTAL:
            raise DesignError(f"more than {MAX_TOTAL // 1024 // 1024} MB at once")
        if name.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise DesignError(f"{name}: not a zip file") from None
            for info in z.infolist():
                if info.is_dir() or "__MACOSX" in info.filename or os.path.basename(info.filename).startswith("."):
                    continue
                if info.file_size > MAX_BYTES:
                    raise DesignError(f"{info.filename}: larger than {MAX_BYTES // 1024} KB")
                total += info.file_size
                if total > MAX_TOTAL:
                    raise DesignError(f"more than {MAX_TOTAL // 1024 // 1024} MB at once")
                parts = info.filename.replace("\\", "/").split("/")
                folder = next((p for p in reversed(parts[:-1]) if ALIASES.get(p, p) in KINDS), None)
                out.append(_check(parts[-1], z.read(info), folder))
        else:
            out.append(_check(name, data))
        if len(out) > MAX_FILES:
            raise DesignError(f"more than {MAX_FILES} designs at once")
    if not out:
        raise DesignError("no designs in what was sent")
    return out


def install(files):
    """Put the designs in the user folder (all or nothing). Returns [{kind, id, replaces}]."""
    designs = unpack(files)  # every file checked before anything is written
    done = []
    for kind, did, text in designs:
        folder = os.path.join(config.USER_DESIGNS_DIR, kind)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{did}.{KINDS[kind]}")
        builtin = os.path.isfile(os.path.join(config.DESIGNS_DIR, kind, f"{did}.{KINDS[kind]}"))
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
        done.append({"kind": kind, "id": did, "replaces": "builtin" if builtin else None})
    return done


def remove(kind, did):
    """Delete one of your designs (built-in ones can't be). True if there was one."""
    if kind not in KINDS or not ID.match(did or ""):
        return False
    path = os.path.join(config.USER_DESIGNS_DIR, kind, f"{did}.{KINDS[kind]}")
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def mine():
    """Your designs, every kind: [{kind, id, name, replaces?}]."""
    # the folder decides the kind (a header's own "@kind theme" must not override "themes")
    return [{**m, "kind": k} for k in KINDS for m in catalog(k) if m["source"] == "user"]


# ---------------- live reload while designing ----------------
def snapshot():
    """{(kind, id): (source, mtime)} of the design that is in use for each id: a change in any of
    them (or a design added or removed) is what live reload reports."""
    out = {}
    for root, src in reversed(roots()):  # yours last: it is the one in use
        for kind, ext in KINDS.items():
            try:
                entries = list(os.scandir(os.path.join(root, kind)))
            except OSError:
                continue
            for e in entries:
                did, x = os.path.splitext(e.name)
                if x == "." + ext and ID.match(did):
                    try:
                        out[(kind, did)] = (src, e.stat().st_mtime_ns)
                    except OSError:
                        pass
    return out


def changes(prev, cur):
    """What live reload tells the page: which designs changed, and whether the lists of designs
    themselves changed (one added or removed: the page reloads to pick up the new lists)."""
    changed = sorted(k for k in set(prev) | set(cur) if prev.get(k) != cur.get(k))
    return {"changed": [{"kind": k, "id": i} for k, i in changed], "catalog": set(prev) != set(cur)}
