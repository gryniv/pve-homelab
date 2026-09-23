// Backgrounds: the SVG landscape scene (index.html .land, built in) plus drop-in CSS ones
// from web/backgrounds/<id>.css, listed by the backend (/api/public → backgrounds).
// layer() is shared by the page and the settings previews ("mini monitors").
import { esc, t } from './ui.js';
import * as clocks from './clocks.js';

const BUILTIN = [
  { id: 'scene', group: 'scape', order: 0, key: 'set.look.bg_scene' },
  { id: 'still', group: 'scape', order: 1, key: 'set.look.bg_still' },
];
let mods = [];

export function init(list) {
  mods = list || [];
  for (const m of mods) {
    if (document.getElementById('bg-css-' + m.id)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = `/backgrounds/${m.id}.css`; l.id = 'bg-css-' + m.id;
    document.head.appendChild(l);
  }
  // The page background mirrors <body>'s time of day and weather.
  new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ['data-tod', 'data-wx'] });
  sync();
}

const pick = (item, lang) => (item && typeof item === 'object' ? item[lang] || item.en || Object.values(item)[0] : item) || '';
export const all = () => [...BUILTIN, ...mods];
export const byGroup = (g) => all().filter((b) => (b.group || 'flat') === g);
export const nameOf = (b, lang) => (b.key ? t(b.key) : pick(b.name, lang));
const meta = (k) => mods.find((m) => m.id === k);
export const isCss = (k) => !!meta(k);

function sync() {
  const { tod, wx } = document.body.dataset;
  document.querySelectorAll('.land, #bgHost > .bgx').forEach((el) => {
    el.dataset.tod = el.dataset.fixedTod || tod;
    el.dataset.wx = wx;
  });
}

export function layer(k) {
  const m = meta(k);
  if (!m) return '<span class="landpv" data-land></span>';
  const fixed = m.tod ? ` data-fixed-tod="${esc(m.tod)}" data-tod="${esc(m.tod)}"` : '';
  return `<span class="bgx${m.group === 'scape' ? ' scape' : ''}" data-k="${esc(k)}"${fixed}><i class="stars"></i><i class="sun"></i><i class="cl"></i><i class="cl cl2"></i><i class="l1"></i><i class="l2"></i><i class="l3"></i><i class="l4"></i><i class="fg"></i><i class="wx"></i></span>`;
}

// Full-screen background of the page.
export function apply(k) {
  const host = document.querySelector('#bgHost');
  if (!host || host.dataset.k === k) return;
  host.dataset.k = k;
  host.innerHTML = isCss(k) ? layer(k) : '';
  sync();
}

/* ---------------- mini monitor ---------------- */

// A tiny monitor: the background under the sign-in screen (or the dashboard) in the given
// theme, clock design and fonts. `look` = {skin, bg, clock, fonts: {ui, display}}.
export function mini(look, fontCss = {}) {
  const style = [fontCss.ui && `--font-ui:${fontCss.ui}`, fontCss.display && `--font-display:${fontCss.display}`].filter(Boolean).join(';');
  return `<span class="mon"><span class="scrn" data-skin="${esc(look.skin)}" data-mode="login" style="${esc(style)}" data-clock-id="${esc(look.clock || 'digital')}">${layer(look.bg)}
    <span class="pvfx"></span><span class="mock">
    <span class="mk-login"><b class="hl"></b><span class="clock ck"></span><b class="dt"></b><b class="w1"></b><b class="w2"></b>
      <b class="who"></b><b class="u"><b></b><b></b><b></b></b><b class="pw"></b><b class="go"></b></span>
    <span class="mk-dash"><i class="tp"></i><i class="sd"></i><i class="sy"><b></b><b></b><b></b><b></b></i><i class="gr">${'<b></b>'.repeat(10)}</i></span>
    </span><span class="cap"></span><span class="pdots"><i></i><i></i><i></i><i></i></span></span></span>`;
}

// After tiles are in the DOM: copy the SVG scene into scene previews, draw the clocks,
// set the live weather, and wire the hover presentation.
export function hydrate(root, locale) {
  const svg = document.querySelector('.land svg');
  root.querySelectorAll('[data-land]').forEach((el) => { if (svg && !el.firstChild) el.appendChild(svg.cloneNode(true)); });
  const now = new Date();
  root.querySelectorAll('.scrn').forEach((scrn) => {
    setFrame(scrn, null);
    clocks.paint(scrn.querySelector('.ck'), scrn.dataset.clockId, now, locale);
    const tile = scrn.closest('button, .tile') || scrn;
    tile.addEventListener('pointerenter', () => present(scrn));
    tile.addEventListener('focus', () => present(scrn));
    tile.addEventListener('pointerleave', () => stop(scrn));
    tile.addEventListener('blur', () => stop(scrn));
  });
}

// What a hover shows, in turn: the picture in clear weather, bad weather, night, and the windows.
const FRAMES = [
  { tod: 'day', wx: 'clear', mode: 'login', cap: 'pv.clear' },
  { tod: 'day', wx: 'thunder', mode: 'login', cap: 'pv.storm' },
  { tod: 'night', wx: 'clear', mode: 'login', cap: 'pv.night' },
  { tod: null, wx: null, mode: 'dash', cap: 'pv.windows' },
];

function setFrame(scrn, f, i = -1) {
  const tod = f?.tod || document.body.dataset.tod || 'dusk';
  const wx = f?.wx || document.body.dataset.wx || 'partly';
  const bg = scrn.querySelector('.bgx, .landpv');
  if (bg) { bg.dataset.tod = bg.dataset.fixedTod || tod; bg.dataset.wx = wx; }
  scrn.dataset.wx = wx;
  scrn.dataset.mode = f?.mode || 'login';
  scrn.querySelector('.cap').textContent = f ? t(f.cap) : '';
  scrn.querySelectorAll('.pdots i').forEach((d, j) => d.classList.toggle('on', j === i));
}

function present(scrn) {
  if (scrn._pv) return;
  scrn.classList.add('live');
  let i = 0;
  const step = () => { setFrame(scrn, FRAMES[i], i); i = (i + 1) % FRAMES.length; };
  step();
  scrn._pv = setInterval(step, 2200);
}

function stop(scrn) {
  clearInterval(scrn._pv);
  scrn._pv = null;
  scrn.classList.remove('live');
  setFrame(scrn, null);
}
