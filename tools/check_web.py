#!/usr/bin/env python3
"""Static checks of the front end, for CI and before a commit:

  - every ES module under web/ and kiosk/ext parses (node --check);
  - every language in web/i18n has the same keys as en.json (plural forms such as
    "cores.few" may exist only where the language needs them);
  - every widget's own i18n block has the same keys in each language.

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
             if "/vendor/" not in f] + glob.glob(os.path.join(ROOT, "kiosk", "ext", "*.js"))
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
    """Widgets carry `i18n: { en: {...}, uk: {...} }`; compare the key names per language."""
    errors = []
    for path in sorted(glob.glob(os.path.join(ROOT, "web", "widgets", "*", "widget.js"))):
        src = open(path, encoding="utf-8").read()
        blocks = dict(re.findall(r"\b(en|uk)\s*:\s*\{([^{}]*)\}", src))
        if len(blocks) < 2:
            continue
        # keys only: blank out string literals first, their text may contain "word:" too
        no_str = {lang: re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`", "''", body) for lang, body in blocks.items()}
        keys = {lang: set(re.findall(r"([A-Za-z_]\w*)\s*:", body)) for lang, body in no_str.items()}
        if keys["en"] != keys["uk"]:
            w = os.path.basename(os.path.dirname(path))
            errors.append(f"widgets/{w}: en/uk keys differ: {sorted(keys['en'] ^ keys['uk'])}")
    return errors


def main():
    errors = check_js() + check_i18n() + check_widget_i18n()
    for e in errors:
        print("  " + e)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
