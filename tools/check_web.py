#!/usr/bin/env python3
"""Static checks of the front end, for CI and before a commit:

  - every ES module under web/ and kiosk/ext parses (node --check);
  - every language in web/i18n has the same keys as en.json (plural forms such as
    "cores.few" may exist only where the language needs them);
  - every built-in widget keeps its strings in i18n/<lang>.json next to widget.js (not in the
    code), en.json has its title, and every language has the same keys as en.json.

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


def main():
    errors = check_js() + check_i18n() + check_widget_i18n()
    for e in errors:
        print("  " + e)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
