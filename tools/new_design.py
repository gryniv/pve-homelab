#!/usr/bin/env python3
"""Start a new design from a built-in one, ready to edit.

    python3 tools/new_design.py theme neon-night                 # a copy of the Dusk theme
    python3 tools/new_design.py background my-hills --from hills
    python3 tools/new_design.py clock big --name "Big" --name-uk "Великий"
    python3 tools/new_design.py font my-font --from onest
    python3 tools/new_design.py widget host                      # your own look for the host widget

The copy gets the new id everywhere it is used (data-skin="…", data-k="…", data-clockk="…"),
a header with @kind and the names, and lands in your designs folder: by default the demo's
(.demo/state/designs), so a running demo (./demo.sh) shows it at once and, with live reload,
updates it on every save. --to picks another folder: the host's /etc/pve-homelab/designs, a git
repository of your designs (then run the demo with --designs DIR), or designs/ to add a built-in one.

Prints where the file is and the showcase address that shows it in every state.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

KINDS = {"theme": ("themes", "css", "dusk"), "background": ("backgrounds", "css", "mountains"),
         "clock": ("clocks", "js", "digital"), "font": ("fonts", "css", "onest"), "widget": ("widgets", "css", None)}
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# where the id appears inside a design, per kind: the copy is renamed there
SELECTOR = {"themes": r'(data-skin=")({old})(")', "backgrounds": r'(data-k=")({old})(")', "clocks": r'(data-clockk=")({old})(")'}


def header(kind, did, names, src_header):
    """A fresh first comment: @kind, the names, and the source's other keys (@group, @family …)."""
    keep = [line for line in re.findall(r"@(\w+(?:\.\w+)?)[ \t]+([^\n*]+)", src_header)
            if not line[0].startswith(("name", "desc", "kind", "order"))]
    lines = [f"@kind {kind[:-1]}"] + [f"@name.{lang} {n}" for lang, n in names.items()]
    lines += [f"@{k} {v.strip()}" for k, v in keep] + ["@order 90"]
    return "/*\n" + "".join(f" * {line}\n" for line in lines) + " */\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=list(KINDS))
    ap.add_argument("id", help="lower-case letters, digits, - or _ (for a widget: the widget's id)")
    ap.add_argument("--from", dest="src", help="the built-in design to start from")
    ap.add_argument("--to", default=os.path.join(ROOT, ".demo", "state", "designs"), help="designs folder (default: the demo's)")
    ap.add_argument("--name", help="English name (default: from the id)")
    ap.add_argument("--name-uk", help="Ukrainian name")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    a = ap.parse_args()

    folder, ext, default_src = KINDS[a.kind]
    if not ID.match(a.id):
        sys.exit(f"{a.id}: use lower-case letters, digits, - or _")
    src_id = a.src or default_src or a.id  # a widget's look starts from that widget's own
    src = os.path.join(ROOT, "designs", folder, f"{src_id}.{ext}")
    if not os.path.isfile(src):
        have = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(ROOT, "designs", folder)))
        sys.exit(f"no built-in {a.kind} called {src_id}; there are: {', '.join(have)}")
    if a.kind == "widget" and not os.path.isfile(os.path.join(ROOT, "web", "widgets", a.id, "widget.js")):
        sys.exit(f"no widget called {a.id}: a widget's look takes the widget's id")
    text = open(src, encoding="utf-8").read()
    m = re.match(r"\s*/\*(.*?)\*/\n?", text, re.S)
    body = text[m.end():] if m else text
    if folder in SELECTOR and src_id != a.id:
        body = re.sub(SELECTOR[folder].format(old=re.escape(src_id)), lambda x: x.group(1) + a.id + x.group(3), body)
    names = {"en": a.name or a.id.replace("-", " ").replace("_", " ").capitalize()}
    if a.name_uk:
        names["uk"] = a.name_uk
    out = os.path.join(os.path.abspath(a.to), folder, f"{a.id}.{ext}")
    if os.path.exists(out) and not a.force:
        sys.exit(f"{out} already exists (--force to overwrite)")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(header(folder, a.id, names, m.group(1) if m else "") + body)
    print(out)
    if a.kind != "widget":
        print(f"showcase: http://127.0.0.1:8900/?seat=igpu&showcase={folder}:{a.id}")
    else:
        print("see it on the dashboard with the widget added (Settings > Dashboard)")


if __name__ == "__main__":
    main()
