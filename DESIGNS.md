# Designs

*[Українською](DESIGNS.uk.md)*

How the menu looks lives apart from the program: colours, backgrounds, clocks, fonts and the
look of each widget. A design is **one file**; drop it in a folder and it shows up in
*Settings → Look* with a live preview.

- **Built-in designs** ship in `designs/` and are replaced by updates.
- **Your own** live in `/etc/pve-homelab/designs/<kind>/` on the host. Updates never touch that
  folder, and a file there with the same id as a built-in design replaces it.
- Admins can also install them from the menu: *Settings → Look → My designs → Install designs…*
  takes one or more `.css` / `.js` files, or a `.zip` with several (in kind folders such as
  `themes/…`, or loose with `@kind` in each file).

| Kind | File | What it is |
|---|---|---|
| Theme | `themes/<id>.css` | colours and the display font, as CSS custom properties |
| Background | `backgrounds/<id>.css` | what is behind the sign-in screen and the dashboard |
| Clock | `clocks/<id>.js` | how the time is drawn (a small ES module) |
| Font | `fonts/<id>.css` | a web font to pick for the interface or the clock |
| Widget look | `widgets/<id>.css` | how widget `<id>` looks; its logic is a widget, built in or [your own](#your-own-widgets) |

The id is the file name: lower-case letters, digits, `-` and `_`.

## Working on a design

```bash
./demo.sh                                              # the demo, with live reload
python3 tools/new_design.py theme neon-night           # a copy of a built-in one, renamed
# edit .demo/state/designs/themes/neon-night.css and save:
# the open demo changes at once, no reload
open "http://127.0.0.1:8900/?seat=igpu&showcase=themes:neon-night"
```

- **`tools/new_design.py <kind> <id>`** starts from a built-in design (`--from` picks which) with
  the new id wherever the design uses it and a header with `@kind` and the names (`--name`,
  `--name-uk`). It writes to the demo's designs folder unless `--to` says otherwise.
- **Your own folder of designs**, say a git repository: `./demo.sh --designs ~/my-designs` and
  `new_design.py … --to ~/my-designs`. Copy the files to `/etc/pve-homelab/designs/` on the host,
  or install them from the menu.
- **Live reload** is on in the demo. When a file is saved, its stylesheet or clock is swapped in
  place; when a design is added or removed, the page reloads. On a host it is off unless
  `designer: true` is in `config.yaml`.
- **The showcase**, `?showcase=<kind>:<id>` (themes, backgrounds, clocks, fonts), shows one design
  in every state at once: day, rain, storm, dusk, night, snow, and the dashboard by day and by
  night. A theme is shown on several backgrounds; a background, clock or font in several
  themes. Esc closes it. A widget's look shows on the dashboard with the widget added.

## The header

Every design starts with a comment, **one `@key` per line**:

```css
/*
 * @kind theme
 * @name.en Neon night
 * @name.uk Неонова ніч
 * @desc.en cold, electric
 * @order 20
 */
```

| Key | Meaning |
|---|---|
| `@kind` | `theme`, `background`, `clock`, `font` or `widget`. Needed when a file comes loose (not in a kind folder); `new_design.py` always writes it |
| `@name.<lang>` | the name in the settings, per language (`@name` alone means English) |
| `@desc.<lang>` | a short description under the name |
| `@order` | position in the list, lower first (built-in ones use 10 to 160) |
| `@group` | backgrounds: `scape` (a landscape: the engine adds sun, moon, stars, clouds, fog, weather) or `flat` |
| `@tod` | backgrounds: always this time of day (`night`, `dawn`, `day`, `dusk`) |
| `@family` | fonts: the CSS font-family value, e.g. `"Onest", sans-serif` |
| `@background`, `@clock` | themes: the background and clock that come with it ([a theme as a whole](#a-theme-as-a-whole)) |
| `@option`, `@option.<lang>` | themes: a setting of its own, and what a language calls it and its values |

## Theme

Custom properties, set on the theme's selector; everything else derives from them. A theme may
also restyle widgets or [move things around](#moving-things-around), as long as **every rule stays
under its own `[data-skin="<id>"]`**: all themes are loaded at once and the page picks one, so a
rule without it would change every other theme too. The installer refuses such a theme.

```css
.A[data-skin="neon-night"],.A [data-skin="neon-night"]{
  --acc:#00e5ff;            /* the accent: buttons, highlights, the sky's tint */
  --acc2:#ff3df0;           /* a second accent: the sky's glow, gradients */
  --acc-ink:#001418;        /* text on an accent background */
  --acc-text:#7ff3ff;       /* accent-coloured text on dark */
  --acc-soft:rgba(0,229,255,.14);   /* tinted backgrounds */
  --acc-line:rgba(0,229,255,.7);    /* accent borders */
  --glass:rgba(16,22,31,.62);       /* panels */
  --solid:radial-gradient(80em 50em at 80% 120%,#2a0b3a,#05070f 60%);  /* the "theme" background */
  --display:"Onest",system-ui,sans-serif;   /* clock and headings, unless the user picks a font */
  --lf:saturate(1);         /* a filter on the built-in SVG landscape */
}
```

### A theme as a whole

A theme can stand on its own: name the background and the clock that go with it, and offer a few
settings of its own, such as its colour, its font or where things sit. Picking it in *Settings →
Look* brings the background and clock along and resets the fonts to the theme's own; everything can
still be changed afterwards on its tab. The settings show under the theme tiles.

```css
/*
 * @kind theme
 * @name.en Phosphor
 * @background vector
 * @clock tty
 * @option color = amber | green
 * @option.en color Phosphor: amber | green
 * @option.uk color Люмінофор: бурштиновий | зелений
 */
.A[data-skin="phosphor"],.A [data-skin="phosphor"]{--acc:#ffb000}
.A[data-skin="phosphor"][data-o-color="green"]{--acc:#33ff77}
```

- `@option <key> = <value> | <value> …`: up to 6 settings of 2–8 values each; the first value is
  the default. Keys and values are lower-case letters, digits and `-`.
- `@option.<lang> <key> <Name>: <name> | <name> …` names the setting and its values in that
  language, in the same order; a line whose count doesn't match keeps the name and drops the values'.
- The page carries the chosen value as `data-o-<key>`, so the theme's CSS reads it like any other
  attribute, under its own `[data-skin]`. A value it doesn't know falls back to the default.
- The settings are kept per person and per theme, and the sign-in screen shows each person's.

## Background

Paint `.bgx[data-k="<id>"]` and, for a landscape, the layers inside it, back to front:
`.stars .sun .cl .cl2 .l1 .l2 .l3 .l4 .fg .wx`. You paint `.bgx` itself and whichever of
`.l1`–`.l4` you need; with `@group scape` the engine draws the sun or moon, stars, clouds, fog
and the weather for you.

Use the palette, which already follows the theme and the time of day:
`--sky1 --sky2 --sky3` (top to horizon), `--far --mid --ink` (hills from far to near).

React to the moment with attributes on `.bgx`:

- `data-tod`: `night`, `dawn`, `day`, `dusk`
- `data-wx`: `clear`, `partly`, `overcast`, `rain`, `thunder`, `snow`, `fog`

```css
.bgx[data-k="my-hills"]{background:linear-gradient(180deg,var(--sky1),var(--sky2) 50%,var(--sky3))}
.bgx[data-k="my-hills"] .l1{left:0;right:0;top:55%;bottom:0;background:var(--mid);
  clip-path:polygon(0 40%,30% 10%,60% 35%,100% 15%,100% 100%,0 100%)}
.bgx[data-k="my-hills"][data-wx="snow"] .l1{background:linear-gradient(180deg,#eef3f8 0 15%,var(--mid) 40%)}
```

Good examples: `designs/backgrounds/mountains.css` (a landscape), `gradient.css` (flat).

## Clock

An ES module with two exports. `render` is called every second and should only touch what
changed.

```js
export const css = `
  [data-clockk="big"]{font-size:1.2em;letter-spacing:.05em}
`;                                   // scoped to this clock by [data-clockk="<id>"]

export function render(el, t) {      // t = {h, m, s, text: "HH:MM", date: Date}
  if (el.textContent !== t.text) el.textContent = t.text;
}
```

Good examples: `designs/clocks/digital.js` (the simplest), `flip.js`, `analog.js`.

## Font

```css
/*
 * @kind font
 * @name My font
 * @family "My Font", sans-serif
 */
@import url("https://fonts.googleapis.com/css2?family=My+Font:wght@400;600;800&display=swap");
```

It is loaded only when someone picks it or opens its preview.

## Widget look

Styles for `.A .w[data-w="<id>"]`, where `<id>` is the widget's id. A widget's own classes are
its own; the quickest start is a copy of the built-in look:
`python3 tools/new_design.py widget host`.

## Moving things around

A theme can rearrange the screens, not only colour them: the sign-in form on the left, the top bar
at the bottom like a terminal's status line, the side column on the right. Hook onto these parts
only. They keep their names and what they hold across updates (where they sit in the markup may
change); any other class of the menu is its own business and may change without notice.

| Hook | Screen | What it holds |
|---|---|---|
| `[data-scr="saver"]`, `[data-scr="login"]`, `[data-scr="dash"]` | | the screens themselves |
| `[data-part="saver-time"]`, `[data-part="saver-weather"]` | screensaver | the clock and date; the weather |
| `[data-part="login-intro"]` | sign-in | the host line, title, clock and date, and the widgets |
| `[data-part="login-widgets"]` | sign-in | the widget column (inside `login-intro`) |
| `[data-part="login-form"]` | sign-in | who is signing in, the password |
| `[data-part="login-about"]`, `[data-part="login-power"]` | sign-in | the version line; the language and screensaver buttons |
| `[data-part="topbar"]` | dashboard | the bar: `brand`, `open-tabs`, `topbar-tools` |
| `[data-part="dash-body"]` | dashboard | all below the bar: `sidecol` and `dash-main` |
| `[data-part="sidecol"]` | dashboard | the side widget column |
| `[data-part="dash-main"]` | dashboard | `systems` and `services` |
| `[data-part="systems"]`, `[data-part="services"]` | dashboard | the systems row; the web services and guests tabs |

```css
/* the top bar at the bottom, the sign-in form on the left */
@media (min-width: 901px) {
  .A[data-skin="tmux"] [data-part="topbar"]{position:absolute;left:0;right:0;bottom:0;border-top:1px solid var(--edge);border-bottom:0}
  .A[data-skin="tmux"] [data-part="dash-body"]{top:0;bottom:3.6em}
  .A[data-skin="tmux"] [data-scr="login"]{grid-template-columns:28em 1fr}
  .A[data-skin="tmux"] [data-part="login-form"]{order:-1}
}
```

- **Keep it in `@media (min-width: 901px)`.** Under 900 px the menu has its own one-column layout
  for phones and upright tablets.
- **Scope to the page, `.A[data-skin="<id>"]`** (no space before the bracket), so the small
  previews in *Settings → Look* stay as they are.
- **The keyboard:** arrows go by what is on screen, so they follow you; Tab goes by the markup,
  so it jumps when parts move far. Try both in the showcase and the demo.

## Your own widgets

A widget is the part with logic: what it reads and what it shows. The built-in ones are in
`web/widgets/<id>/widget.js`; yours live in `/etc/pve-homelab/widgets/<id>/widget.js` on the host,
are kept by updates, and show up in *Settings → Dashboard* (or *Sign-in screen*) next to the
built-in ones. The id can't be a built-in widget's. Its look is a design like any other,
`widgets/<id>.css`.

```bash
./demo.sh
python3 tools/new_widget.py uptime            # .demo/state/widgets/uptime/: widget.js, i18n/en.json,
                                              # i18n/uk.json, and its look in designs/widgets/uptime.css
# add "Uptime" in Settings → Dashboard, then edit: saving the widget or its strings reloads
# the page, saving its look restyles it in place
python3 tools/new_widget.py uptime --to ~/my-widgets   # a folder laid out like /etc/pve-homelab
./demo.sh --widgets ~/my-widgets/widgets --designs ~/my-widgets/designs
```

The new widget is a working example of each part of the contract: it reads `/api/host`, has an
option and strings in English and Ukrainian.

```
widgets/uptime/
  widget.js          the code
  i18n/en.json       its strings, one file per language
  i18n/uk.json
```

```js
export default {
  zones: ['side', 'login'],          // where it may be placed
  public: true,                      // allowed on the sign-in screen (it reads only public data)
  source: '/api/host', every: 10,    // what it reads (a GET of the menu's API, or (ctx) => Promise) and how often (s)
  options: [                         // a ⚙ form with a live preview in Settings; label: a key of its strings
    { key: 'load', type: 'toggle', label: 'opt_load', default: true },
  ],                                 // toggle · select · checks · number · text · date · list · textarea
  render: (data, { t, ui, opts }) => `<h4>${ui.esc(t('title'))}</h4>…`,   // returns HTML
  after: (el, data, ctx) => {},      // optional: wire up the rendered element
};
```

```json
{
  "title": "Uptime",
  "opt_load": "Show the load",
  "up": "up {d} d {h} h",
  "things": { "one": "{n} thing", "other": "{n} things" }
}
```

`t('key')` reads the widget's strings in the person's language (English when a key is missing
there), `t('up', { d: 3, h: 4 })` fills in `{d}` and `{h}`, and a key with `one`/`few`/`many`/
`other` picks the plural form for `{n}`. `title` names the widget in Settings. A new language is
a new file, `i18n/pl.json`; one in your folder (`/etc/pve-homelab/widgets/weather/i18n/pl.json`)
also adds a language to a built-in widget. An `i18n: { en: {…} }` block in the module still works
for widgets written that way, with the files taking precedence.

`ctx` also has `app` (the menu: `app.prefs()`, `app.api`, …) and `zone`. Escape anything that comes
from data with `ui.esc`. When `render` throws or `source` fails, the widget shows the error with
a retry button and the error journal (*Settings → About*) records it.

**Installing on a host:** copy the files into `/etc/pve-homelab` (same layout), or, as an admin,
*Settings → Dashboard → My widgets → Install widgets…* with `<id>.js`, its look `<id>.css` and its
strings `<id>.en.json`, `<id>.uk.json` …, or a `.zip`: of widget folders (`<id>/widget.js`,
`<id>/widget.css`, `<id>/i18n/<lang>.json`), of a folder laid out like `/etc/pve-homelab`
(`widgets/<id>/…`, `designs/widgets/<id>.css`), or with `widget.js` and `i18n/` on top, then named
like the zip. `new_widget.py` prints the `zip` command. Installing again replaces the code, and
the strings of each language sent; the other languages stay.

**A widget is code.** It runs in the menu with the rights of whoever is signed in, and its file is
served to anyone who can open the menu, like the built-in ones: keep secrets out of it. That is
why only admins may install one, and why it is worth installing only widgets you wrote or trust.

## Limits

A design file is at most 512 KB of UTF-8 text; one install takes up to 50 designs and 8 MB. A
widget's `widget.js` is at most 256 KB, a language file 64 KB.
Installing and removing need `Sys.Modify` on `/` in Proxmox: a design changes the menu for
everyone on the host, and a clock is code that runs in the menu.
