"""Your own widgets, next to the built-in ones.

    web/widgets/<id>/widget.js                    built-in (replaced by updates)
    /etc/pve-homelab/widgets/<id>/widget.js       yours (kept by updates)
    <either>/<id>/i18n/<lang>.json                the widget's strings, one file per language

A widget's strings live apart from its code: i18n/en.json, i18n/uk.json … next to widget.js, flat
{"key": "text"} (or {"one": …, "few": …, "other": …} for plurals). Files in your folder add to
or override those of a built-in widget with the same id: a language of your own, say.

A widget's look is a design: designs/widgets/<id>.css, or yours in
/etc/pve-homelab/designs/widgets/<id>.css. Installing a widget from the menu can bring its look
along. An id of yours can't be a built-in widget's: those are part of the program.

A widget is code that runs in the menu with the signed-in person's rights, which is why only
admins may install one.
"""

import io
import json
import os
import re
import shutil
import zipfile

from . import config, designs

ID = designs.ID
LANG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
MAX_JS = 256 * 1024
MAX_I18N = 64 * 1024


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


def roots():
    """Where widgets live, built-in first (yours override its strings)."""
    return [os.path.join(config.WEB_DIR, "widgets"), config.USER_WIDGETS_DIR]


def _strings(text):
    """A language file's text -> {key: str | {plural form: str}}, or WidgetError."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise WidgetError(f"not valid JSON ({e})") from None
    if not isinstance(data, dict):
        raise WidgetError("must be a JSON object of \"key\": \"text\"")
    for k, v in data.items():
        ok = isinstance(v, str) or (isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()))
        if not ok:
            raise WidgetError(f"{k}: a text, or plural forms {{\"one\": …, \"other\": …}}")
    return data


def translations():
    """{id: {lang: {key: text}}} for every widget with language files; a broken file is skipped."""
    out = {}
    for root in roots():
        try:
            ids = [d for d in os.listdir(root) if ID.match(d)]
        except OSError:
            continue
        for wid in ids:
            folder = os.path.join(root, wid, "i18n")
            try:
                files = sorted(os.listdir(folder))
            except OSError:
                continue
            for f in files:
                lang, ext = os.path.splitext(f)
                if ext != ".json" or not LANG.match(lang):
                    continue
                try:
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        text = fh.read(MAX_I18N + 1)
                    if len(text) > MAX_I18N:
                        continue
                    strings = _strings(text)
                except (OSError, UnicodeDecodeError, WidgetError):
                    continue
                out.setdefault(wid, {}).setdefault(lang, {}).update(strings)
    return out


def mine():
    """Your widgets: [{id, look, languages}] (the menu takes the title from the widget's strings)."""
    out = []
    for wid in sorted(user_ids()):
        try:
            langs = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(config.USER_WIDGETS_DIR, wid, "i18n"))
                           if f.endswith(".json"))
        except OSError:
            langs = []
        out.append({"id": wid, "look": os.path.isfile(os.path.join(config.USER_DESIGNS_DIR, "widgets", f"{wid}.css")),
                    "languages": langs})
    return out


def snapshot():
    """{path: mtime} of your widgets' code and strings: live reload reloads the page when one
    changes (a module once imported can't be swapped in place)."""
    out = {}
    try:
        ids = [d for d in os.listdir(config.USER_WIDGETS_DIR) if ID.match(d)]
    except OSError:
        return out
    for wid in ids:
        folder = os.path.join(config.USER_WIDGETS_DIR, wid)
        paths = [os.path.join(folder, "widget.js")]
        try:
            paths += [os.path.join(folder, "i18n", f) for f in os.listdir(os.path.join(folder, "i18n"))]
        except OSError:
            pass
        for p in paths:
            try:
                out[p] = os.stat(p).st_mtime_ns
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
    """[(name, bytes)] -> {id: {"js": text, "css": text|None, "i18n": {lang: text}}}.
    Loose files: <id>.js, its look <id>.css, its strings <id>.<lang>.json. Or a .zip with
    <id>/widget.js, <id>/widget.css and <id>/i18n/<lang>.json (a folder laid out like
    /etc/pve-homelab, with the look in designs/widgets/<id>.css, works too), or loose files as
    above; several widgets in one zip are fine. A zip's widget.js at its top is the widget named
    like the zip. Inside a zip, a stylesheet or strings with no widget of their id are left out
    (some other design, some other file)."""
    found, total, zip_css, zip_json = {}, 0, {}, []

    def entry(wid):
        return found.setdefault(wid, {"js": None, "css": None, "i18n": {}})

    def add(wid, kind, name, data, lang=None):
        if kind == "js":
            _check_id(wid, name)
            text = _text(name, data, MAX_JS)
            if not re.search(r"\bexport\s+default\b", text):
                raise WidgetError(f"{name}: a widget is an ES module with `export default {{ … }}`")
            entry(wid)["js"] = text
        elif kind == "json":
            if not LANG.match(lang or ""):
                raise WidgetError(f"{name}: strings go in <id>.<lang>.json, e.g. uptime.uk.json")
            text = _text(name, data, MAX_I18N)
            try:
                _strings(text)
            except WidgetError as e:
                raise WidgetError(f"{name}: {e}") from None
            entry(wid)["i18n"][lang] = text
        else:
            entry(wid)["css"] = _text(name, data, designs.MAX_BYTES)

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
                if ext not in (".js", ".css", ".json"):
                    continue
                if info.file_size > max(MAX_JS, designs.MAX_BYTES):
                    raise WidgetError(f"{info.filename}: too large")
                total += info.file_size
                if total > designs.MAX_TOTAL:
                    raise WidgetError(f"more than {designs.MAX_TOTAL // 1024 // 1024} MB at once")
                here = os.path.splitext(os.path.basename(name))[0]   # the zip's own name
                if ext == ".json":
                    if len(parts) > 1 and parts[-2] == "i18n":        # <id>/i18n/<lang>.json
                        wid, lang = (parts[-3] if len(parts) > 2 else here), base
                    else:                                              # <id>.<lang>.json
                        wid, _, lang = base.partition(".")
                    if LANG.match(lang):                               # else: some other JSON file
                        zip_json.append((wid, info.filename, z.read(info), lang))
                    continue
                if base != "widget":
                    wid = base
                elif len(parts) > 1:
                    wid = parts[-2]
                else:
                    wid = here
                if ext == ".css":
                    zip_css[wid] = (info.filename, z.read(info))
                else:
                    add(wid, "js", info.filename, z.read(info))
        else:
            base, ext = os.path.splitext(os.path.basename(name))
            if ext not in (".js", ".css", ".json"):
                raise WidgetError(f"{name}: a widget is a .js file (with its look, .css, and strings, "
                                  f"<id>.<lang>.json), or a .zip")
            if ext == ".json":
                wid, _, lang = base.partition(".")
                add(wid, "json", name, data, lang)
                continue
            if base == "widget":
                raise WidgetError(f"{name}: name it <id>{ext} (the widget's id), or send a .zip of its folder")
            add(base, ext[1:], name, data)
    for wid, (name, data) in zip_css.items():
        if wid in found and found[wid]["css"] is None:
            add(wid, "css", name, data)
    for wid, name, data, lang in zip_json:
        if wid in found:
            add(wid, "json", name, data, lang)
    for wid, parts in found.items():
        if not parts["js"]:
            raise WidgetError(f"{wid}: a look or strings without the widget (widget.js is missing)")
    if not found:
        raise WidgetError("no widgets in what was sent")
    return found


def install(files):
    """Put the widgets (with their looks and strings) in place, all or nothing; strings sent for a
    language replace that language's file, the others stay. Returns [{id, look, languages}]."""
    found = unpack(files)  # every file checked before anything is written
    done = []
    for wid, parts in sorted(found.items()):
        folder = os.path.join(config.USER_WIDGETS_DIR, wid)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "widget.js")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(parts["js"])
        os.replace(path + ".tmp", path)
        for lang, text in parts["i18n"].items():
            p = os.path.join(folder, "i18n", f"{lang}.json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(p + ".tmp", p)
        if parts["css"] is not None:
            look = os.path.join(config.USER_DESIGNS_DIR, "widgets", f"{wid}.css")
            os.makedirs(os.path.dirname(look), exist_ok=True)
            with open(look + ".tmp", "w", encoding="utf-8") as f:
                f.write(parts["css"])
            os.replace(look + ".tmp", look)
        done.append({"id": wid, "look": parts["css"] is not None, "languages": sorted(parts["i18n"])})
    return done


def remove(wid):
    """Delete one of your widgets (its look, a design, stays until removed there)."""
    if not ID.match(wid or "") or wid not in user_ids():
        return False
    shutil.rmtree(os.path.join(config.USER_WIDGETS_DIR, wid))
    return True
