"""Your own widgets, next to the built-in ones.

    web/widgets/<id>/widget.js                    built-in (replaced by updates)
    /etc/pve-homelab/widgets/<id>/widget.js       yours (kept by updates)

A widget's look is a design: designs/widgets/<id>.css, or yours in
/etc/pve-homelab/designs/widgets/<id>.css. Installing a widget from the menu can bring its look
along. An id of yours can't be a built-in widget's: those are part of the program.

A widget is code that runs in the menu with the signed-in person's rights, which is why only
admins may install one.
"""

import io
import os
import re
import shutil
import zipfile

from . import config, designs

ID = designs.ID
MAX_JS = 256 * 1024


class WidgetError(ValueError):
    """Something that can't be installed as a widget; the message says why."""


def _ids(root):
    try:
        return {d for d in os.listdir(root) if ID.match(d) and os.path.isfile(os.path.join(root, d, "widget.js"))}
    except OSError:
        return set()


def builtin_ids():
    return _ids(os.path.join(config.WEB_DIR, "widgets"))


def user_ids():
    return _ids(config.USER_WIDGETS_DIR) - builtin_ids()


def all_ids():
    return sorted(builtin_ids() | user_ids())


def path_of(wid):
    """widget.js of widget `wid` (built-in or yours), or None."""
    if not ID.match(wid or ""):
        return None
    for root in (os.path.join(config.WEB_DIR, "widgets"), config.USER_WIDGETS_DIR):
        p = os.path.join(root, wid, "widget.js")
        if os.path.isfile(p):
            return p
    return None


def mine():
    """Your widgets: [{id, look}] (the menu takes the title from the widget's own strings)."""
    return [{"id": wid, "look": os.path.isfile(os.path.join(config.USER_DESIGNS_DIR, "widgets", f"{wid}.css"))}
            for wid in sorted(user_ids())]


def snapshot():
    """{id: mtime} of your widgets: live reload reloads the page when one changes (a module once
    imported can't be swapped in place)."""
    out = {}
    for wid in user_ids():
        try:
            out[wid] = os.stat(os.path.join(config.USER_WIDGETS_DIR, wid, "widget.js")).st_mtime_ns
        except OSError:
            pass
    return out


def _text(name, data, limit):
    if len(data) > limit:
        raise WidgetError(f"{name}: larger than {limit // 1024} KB")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise WidgetError(f"{name}: not UTF-8 text") from None


def _check_id(wid, name):
    if not ID.match(wid):
        raise WidgetError(f"{name}: the widget id must be lower-case letters, digits, - or _")
    if wid in builtin_ids():
        raise WidgetError(f"{name}: {wid} is a built-in widget; pick another id")


def unpack(files):
    """[(name, bytes)] -> {id: {"js": text, "css": text|None}}.
    Either <id>.js (and optionally <id>.css), or a .zip with <id>/widget.js (+ <id>/widget.css,
    or widgets/<id>.css as in a folder laid out like /etc/pve-homelab) or <id>.js (+ <id>.css);
    several widgets in one zip are fine. A zip's widget.js at its top is the widget named like the
    zip. Inside a zip, a stylesheet with no widget of its id is left out (it is some other design)."""
    found, total, zip_css = {}, 0, {}

    def add(wid, kind, name, data):
        if kind == "js":
            _check_id(wid, name)
            text = _text(name, data, MAX_JS)
            if not re.search(r"\bexport\s+default\b", text):
                raise WidgetError(f"{name}: a widget is an ES module with `export default {{ … }}`")
        else:
            text = _text(name, data, designs.MAX_BYTES)
        found.setdefault(wid, {"js": None, "css": None})[kind] = text

    for name, data in files:
        total += len(data)
        if total > designs.MAX_TOTAL:
            raise WidgetError(f"more than {designs.MAX_TOTAL // 1024 // 1024} MB at once")
        if name.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise WidgetError(f"{name}: not a zip file") from None
            for info in z.infolist():
                if info.is_dir() or "__MACOSX" in info.filename or os.path.basename(info.filename).startswith("."):
                    continue
                parts = info.filename.replace("\\", "/").split("/")
                base, ext = os.path.splitext(parts[-1])
                if ext not in (".js", ".css"):
                    continue
                if info.file_size > max(MAX_JS, designs.MAX_BYTES):
                    raise WidgetError(f"{info.filename}: too large")
                total += info.file_size
                if total > designs.MAX_TOTAL:
                    raise WidgetError(f"more than {designs.MAX_TOTAL // 1024 // 1024} MB at once")
                if base != "widget":
                    wid = base
                elif len(parts) > 1:
                    wid = parts[-2]
                else:
                    wid = os.path.splitext(os.path.basename(name))[0]
                if ext == ".css":
                    zip_css[wid] = (info.filename, z.read(info))
                else:
                    add(wid, "js", info.filename, z.read(info))
        else:
            base, ext = os.path.splitext(os.path.basename(name))
            if ext not in (".js", ".css"):
                raise WidgetError(f"{name}: a widget is a .js file (with an optional .css look), or a .zip")
            if base == "widget":
                raise WidgetError(f"{name}: name it <id>{ext} (the widget's id), or send a .zip of its folder")
            add(base, ext[1:], name, data)
    for wid, (name, data) in zip_css.items():
        if wid in found and found[wid]["css"] is None:
            add(wid, "css", name, data)
    for wid, parts in found.items():
        if not parts["js"]:
            raise WidgetError(f"{wid}: a look without its widget (widget.js is missing)")
    if not found:
        raise WidgetError("no widgets in what was sent")
    return found


def install(files):
    """Put the widgets (and their looks) in place, all or nothing. Returns [{id, look}]."""
    found = unpack(files)  # every file checked before anything is written
    done = []
    for wid, parts in sorted(found.items()):
        folder = os.path.join(config.USER_WIDGETS_DIR, wid)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "widget.js")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(parts["js"])
        os.replace(path + ".tmp", path)
        if parts["css"] is not None:
            look = os.path.join(config.USER_DESIGNS_DIR, "widgets", f"{wid}.css")
            os.makedirs(os.path.dirname(look), exist_ok=True)
            with open(look + ".tmp", "w", encoding="utf-8") as f:
                f.write(parts["css"])
            os.replace(look + ".tmp", look)
        done.append({"id": wid, "look": parts["css"] is not None})
    return done


def remove(wid):
    """Delete one of your widgets (its look, a design, stays until removed there)."""
    if not ID.match(wid or "") or wid not in user_ids():
        return False
    shutil.rmtree(os.path.join(config.USER_WIDGETS_DIR, wid))
    return True
