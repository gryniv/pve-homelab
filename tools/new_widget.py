#!/usr/bin/env python3
"""Start a widget of your own, ready to edit.

    python3 tools/new_widget.py uptime                      # into the demo (.demo/state)
    python3 tools/new_widget.py uptime --to ~/my-widgets    # a folder of your own, say a git repo

Writes two files, laid out as on the host (/etc/pve-homelab):

    <to>/widgets/<id>/widget.js         the widget: what it reads and what it shows
    <to>/designs/widgets/<id>.css       its look, a design like any other

The new widget reads /api/host every 10 seconds and shows the uptime and the load, with one option
and strings in English and Ukrainian: a working example of each part of the contract. Run the demo
(./demo.sh), add it in Settings → Dashboard, and edit: with live reload on, the page reloads when
the widget is saved and restyles in place when its look is.

To put it on a host: copy both into /etc/pve-homelab (same layout), or zip them as they lie
(cd <to> && zip -r <id>.zip widgets/<id> designs/widgets/<id>.css) and install the zip from
Settings → Dashboard → My widgets → Install widgets…
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

JS = """\
// {title}: the host's uptime and load. A starting point: change what it reads and what it shows.
// The contract is in DESIGNS.md (Your own widgets) and at the top of web/core/widgets.js.
export default {{
  zones: ['side'],          // where it may go: 'side' (dashboard), 'login' (with public: true)
  source: '/api/host',      // what it reads (any GET of the menu's API), or (ctx) => Promise
  every: 10,                // seconds between refreshes
  options: [
    {{ key: 'load', type: 'toggle', label: 'opt_load', default: true }},
  ],
  i18n: {{
    en: {{ title: '{title}', up: 'up {{d}} d {{h}} h', load: 'load {{n}}', opt_load: 'Show the load' }},
    uk: {{ title: '{title}', up: 'працює {{d}} дн. {{h}} год', load: 'навантаження {{n}}', opt_load: 'Показувати навантаження' }},
  }},
  render(data, {{ ui, t, opts }}) {{
    const d = Math.floor(data.uptime / 86400);
    const h = Math.floor((data.uptime % 86400) / 3600);
    return `<h4>${{ui.esc(t('title'))}}</h4>
      <div class="big">${{ui.esc(t('up', {{ d, h }}))}}</div>
      ${{opts.load ? `<div class="mute">${{ui.esc(t('load', {{ n: data.load }}))}}</div>` : ''}}`;
  }},
}};
"""

CSS = """\
/*
 * @kind widget
 * @name.en {title}
 */
.A .w[data-w="{id}"] .big{{font-family:var(--font-display,var(--display));font-size:1.6em;color:var(--acc-text)}}
.A .w[data-w="{id}"] .mute{{font-size:.85em;margin-top:.2em}}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", help="lower-case letters, digits, - or _")
    ap.add_argument("--to", default=os.path.join(ROOT, ".demo", "state"),
                    help="folder laid out like /etc/pve-homelab (default: the demo's)")
    ap.add_argument("--title", help="its title (default: from the id)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    a = ap.parse_args()

    if not ID.match(a.id):
        sys.exit(f"{a.id}: use lower-case letters, digits, - or _")
    if os.path.isfile(os.path.join(ROOT, "web", "widgets", a.id, "widget.js")):
        sys.exit(f"{a.id} is a built-in widget; pick another id "
                 f"(for your own look of it: python3 tools/new_design.py widget {a.id})")
    title = a.title or a.id.replace("-", " ").replace("_", " ").capitalize()
    to = os.path.abspath(os.path.expanduser(a.to))
    files = {os.path.join(to, "widgets", a.id, "widget.js"): JS.format(title=title.replace("'", "\\'")),
             os.path.join(to, "designs", "widgets", f"{a.id}.css"): CSS.format(id=a.id, title=title)}
    for path in files:
        if os.path.exists(path) and not a.force:
            sys.exit(f"{path} already exists (--force to overwrite)")
    for path, text in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(path)
    print(f"to install elsewhere: cd {to} && zip -r {a.id}.zip widgets/{a.id} designs/widgets/{a.id}.css")


if __name__ == "__main__":
    main()
