#!/usr/bin/env python3
"""Static checks of the front end, for CI and before a commit:

  - every ES module under web/ and kiosk/ext parses (node --check);
  - every language in web/i18n has the same keys as en.json (plural forms such as
    "cores.few" may exist only where the language needs them);
  - every built-in widget keeps its strings in i18n/<lang>.json next to widget.js (not in the
    code), en.json has its title, and every language has the same keys as en.json.
  - every key in web/i18n/en.json is used somewhere, and every t('key') the page asks for exists
    (keys built at run time are allowed only under the prefixes in DYNAMIC_OK).

    python3 tools/check_web.py
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLURAL = re.compile(r"\.(zero|one|two|few|many|other)$")


def flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def check_js():
    node = shutil.which("node")
    if not node:
        return ["node not found: JS syntax not checked"]
    errors = []
    files = [f for f in glob.glob(os.path.join(ROOT, "web", "**", "*.js"), recursive=True)
             if "/vendor/" not in f] + glob.glob(os.path.join(ROOT, "designs", "**", "*.js"), recursive=True) \
        + glob.glob(os.path.join(ROOT, "kiosk", "ext", "*.js"))
    with tempfile.TemporaryDirectory() as tmp:
        for f in sorted(files):
            # .mjs: node reads it as an ES module whatever package.json says
            copy = os.path.join(tmp, "check.mjs")
            shutil.copyfile(f, copy)
            r = subprocess.run([node, "--check", copy], capture_output=True, text=True)
            if r.returncode:
                lines = r.stderr.splitlines()
                where = next((ln.split(":")[-1] for ln in lines if ln.startswith(copy + ":")), "?")
                why = next((ln for ln in lines if "Error" in ln), "syntax error")
                errors.append(f"{os.path.relpath(f, ROOT)}:{where}: {why}")
    print(f"js: {len(files)} files")
    return errors


def check_i18n():
    errors = []
    base = flat(json.load(open(os.path.join(ROOT, "web", "i18n", "en.json"), encoding="utf-8")))
    want = {k for k in base if not PLURAL.search(k)}
    for path in sorted(glob.glob(os.path.join(ROOT, "web", "i18n", "*.json"))):
        lang = os.path.basename(path)[:-5]
        keys = {k for k in flat(json.load(open(path, encoding="utf-8"))) if not PLURAL.search(k)}
        for k in sorted(want - keys):
            errors.append(f"i18n/{lang}.json: missing {k}")
        for k in sorted(keys - want):
            errors.append(f"i18n/{lang}.json: {k} is not in en.json")
    print(f"i18n: {len(want)} keys")
    return errors


def check_widget_i18n():
    """Widgets keep their strings in <id>/i18n/<lang>.json; compare the keys with en.json."""
    errors = []
    for path in sorted(glob.glob(os.path.join(ROOT, "web", "widgets", "*", "widget.js"))):
        folder = os.path.dirname(path)
        w = os.path.basename(folder)
        if re.search(r"^\s*i18n\s*:", open(path, encoding="utf-8").read(), re.M):
            errors.append(f"widgets/{w}: strings belong in i18n/<lang>.json, not in widget.js")
        langs = {}
        for f in sorted(glob.glob(os.path.join(folder, "i18n", "*.json"))):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except ValueError as e:
                errors.append(f"widgets/{w}/i18n/{os.path.basename(f)}: {e}")
                continue
            langs[os.path.basename(f)[:-5]] = {k for k in flat(data) if not PLURAL.search(k)}
        if "en" not in langs:
            errors.append(f"widgets/{w}: no i18n/en.json")
            continue
        if "title" not in langs["en"]:
            errors.append(f"widgets/{w}: i18n/en.json has no title")
        for lang, keys in langs.items():
            if keys != langs["en"]:
                errors.append(f"widgets/{w}/i18n/{lang}.json: keys differ from en.json: {sorted(keys ^ langs['en'])}")
    return errors


# Keys built at run time from a prefix: t('wx.' + kind), t(`fb.k_${k}`). Every key under these
# prefixes counts as used. A new prefix fails the check until it is added here, so a key can't hide
# behind string building without someone looking.
# "w." is the widgets' own namespace (w.<id>.<key>, from widgets/<id>/i18n), not web/i18n.
DYNAMIC_OK = ("alerts.", "wx.", "guest.range_", "fb.k_", "demo.via_", "showcase.tod_", "w.", "cfg.", "copy.part_", "launch.hotkey_", "set.input.kind_")
LITERAL = re.compile(r"""(['"`])([a-z_][A-Za-z0-9_.-]*)\1""")
BUILT = re.compile(r"""\bt\(\s*(?:(['"])([a-z][a-z0-9_.-]*)\1\s*\+|`([a-z][a-z0-9_.-]*)\$\{)""")
CALL = re.compile(r"""\bt\(\s*(['"])([a-z_][A-Za-z0-9_.-]*)\1\s*[,)]""")
ATTR = re.compile(r"""data-i18n(?:-[a-z]+)?="([^"$]+)\"""")


def _bare(keys):
    """Plural forms collapse to the key the code asks for: launch.cores.one/.few/.other are
    t('launch.cores'). Only a real group counts (it has .one and .other), so a key such as
    login.other stays itself."""
    groups = {k[:-6] for k in keys if k.endswith(".other") and k[:-6] + ".one" in keys}
    return {PLURAL.sub("", k) if PLURAL.sub("", k) in groups else k for k in keys}


def _web_sources():
    core = [f for f in glob.glob(os.path.join(ROOT, "web", "**", "*.js"), recursive=True)
            if "/vendor/" not in f and "/widgets/" not in f]
    core += glob.glob(os.path.join(ROOT, "web", "*.html")) + glob.glob(os.path.join(ROOT, "designs", "**", "*.js"), recursive=True)
    widgets = glob.glob(os.path.join(ROOT, "web", "widgets", "*", "widget.js"))
    return sorted(core), sorted(widgets)


def check_i18n_usage():
    """Keys of web/i18n/en.json that nothing uses, and keys the code asks for that en.json lacks.
    Used: any quoted string equal to a key, in the page, its modules, the widgets (they fall back
    to these strings) and the clocks; or a key under a prefix the code builds keys from."""
    errors = []
    keys = set(flat(json.load(open(os.path.join(ROOT, "web", "i18n", "en.json"), encoding="utf-8"))))
    bare = _bare(keys) - {"_name"}   # _name: the language's own name, read by the server
    core, widgets = _web_sources()
    used, built = set(), set()
    for f in core + widgets:
        # comments show usage examples (t('launch.cores', ...)), not real lookups
        text = "\n".join(ln for ln in open(f, encoding="utf-8").read().splitlines()
                          if not ln.lstrip().startswith(("//", "*", "/*")))
        rel = os.path.relpath(f, ROOT)
        used.update(m.group(2) for m in LITERAL.finditer(text))
        used.update(ATTR.findall(text))
        for m in BUILT.finditer(text):
            prefix = m.group(2) or m.group(3)
            if not prefix.startswith(DYNAMIC_OK) and prefix not in DYNAMIC_OK:
                errors.append(f"{rel}: key built from '{prefix}' at run time: list the prefix in DYNAMIC_OK "
                              "(tools/check_web.py) or write the keys out")
            built.add(prefix)
        if f in core:
            asked = {m.group(2) for m in CALL.finditer(text)} | set(ATTR.findall(text))
            for k in sorted(asked - bare):
                errors.append(f"{rel}: t('{k}') is not in i18n/en.json")
        else:
            folder = os.path.dirname(f)
            own = set()
            for p in glob.glob(os.path.join(folder, "i18n", "en.json")):
                own = _bare(flat(json.load(open(p, encoding="utf-8"))))
            for k in sorted({m.group(2) for m in CALL.finditer(text)} - own - bare):
                errors.append(f"{rel}: t('{k}') is in neither its i18n/en.json nor web/i18n/en.json")
    for k in sorted(bare):
        if k in used or k.startswith(tuple(p for p in built if p.startswith(DYNAMIC_OK) or p in DYNAMIC_OK)):
            continue
        errors.append(f"i18n/en.json: {k} is never used")
    print(f"i18n usage: {len(core) + len(widgets)} files")
    return errors


def main():
    errors = check_js() + check_i18n() + check_widget_i18n() + check_i18n_usage()
    for e in errors:
        print("  " + e)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
