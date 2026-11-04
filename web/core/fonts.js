// Fonts are drop-in files: designs/fonts/<id>.css with "@family" in the header and an @import
// of the web font (see README: "Add a font"). They load only when used or previewed.

let mods = [];

export function init(list) { mods = list || []; }
export const all = () => mods;

// CSS font-family value for a font id, or '' for "as in the theme".
export function family(id) {
  const m = mods.find((f) => f.id === id);
  if (!m) return '';
  load(id);
  return m.family;
}

export function load(id) {
  if (!id || document.getElementById('font-css-' + id)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = `/fonts/${id}.css`; l.id = 'font-css-' + id;
  document.head.appendChild(l);
}

// {ui, display} font ids → CSS values for --font-ui / --font-display.
export const css = (f = {}) => ({ ui: family(f.ui), display: family(f.display) });

// Apply to the page.
export function apply(f = {}) {
  const c = css(f);
  const s = document.body.style;
  c.ui ? s.setProperty('--font-ui', c.ui) : s.removeProperty('--font-ui');
  c.display ? s.setProperty('--font-display', c.display) : s.removeProperty('--font-display');
}
