# Designs

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
| Widget look | `widgets/<id>.css` | how widget `<id>` looks; its logic stays in `web/widgets/<id>/` |

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

## Theme

Only custom properties, set on the theme's selector. Everything else derives from them.

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

## Limits

A design file is at most 512 KB of UTF-8 text; one install takes up to 50 designs and 8 MB.
Installing and removing need `Sys.Modify` on `/` in Proxmox: a design changes the menu for
everyone on the host, and a clock is code that runs in the menu.
