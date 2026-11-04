// The design showcase: one design in every state at once, for working on it.
//   /?seat=igpu&showcase=themes:neon-night       (themes | backgrounds | clocks | fonts)
// Rows are the moments (day, rain, storm, dusk, night, snow, the dashboard by day and night);
// columns are what it is combined with (a theme on several backgrounds, a background in every
// theme, a clock or a font in several themes). With live reload on, saving the file updates it.
import * as BG from './backgrounds.js';
import * as F from './fonts.js';
import * as clocks from './clocks.js';
import { $, esc, t, locale } from './ui.js';

const FRAMES = [
  { tod: 'day', wx: 'clear', mode: 'login' }, { tod: 'day', wx: 'rain', mode: 'login' },
  { tod: 'day', wx: 'thunder', mode: 'login' }, { tod: 'dusk', wx: 'partly', mode: 'login' },
  { tod: 'night', wx: 'clear', mode: 'login' }, { tod: 'night', wx: 'snow', mode: 'login' },
  { tod: 'day', wx: 'partly', mode: 'dash' }, { tod: 'night', wx: 'partly', mode: 'dash' },
];
const BASE = { skin: 'dusk', bg: 'scene', clock: 'digital', fonts: {} };
const pick = (item, lang) => (item && typeof item === 'object' ? item[lang] || item.en || Object.values(item)[0] : item) || '';

// The design under test, combined with up to `n` others of a second kind.
function columns(kind, id, pub) {
  const themes = pub.themes.map((x) => x.id);
  const some = (list, n = 4) => list.slice(0, n);
  if (kind === 'themes') {
    const bgs = ['scene', ...pub.backgrounds.map((b) => b.id)];
    return some(['scene', 'mountains', 'city', 'gradient'].filter((b) => bgs.includes(b))).map((bg) => ({ label: bg, look: { ...BASE, skin: id, bg } }));
  }
  if (kind === 'backgrounds') return themes.map((skin) => ({ label: skin, look: { ...BASE, skin, bg: id } }));
  if (kind === 'clocks') return some(themes).map((skin) => ({ label: skin, look: { ...BASE, skin, clock: id } }));
  if (kind === 'fonts') return some(themes).map((skin) => ({ label: skin, look: { ...BASE, skin, fonts: { ui: id, display: id } } }));
  return [];
}

let clockTimer = null;

export function close() {
  clearInterval(clockTimer);
  $('#showcase')?.remove();
  const u = new URL(location.href);
  u.searchParams.delete('showcase');
  history.replaceState(null, '', u);
}

export function open(spec, pub) {
  const [kind, id] = String(spec).split(':');
  const lang = locale().slice(0, 2);
  const list = { themes: pub.themes, backgrounds: pub.backgrounds, clocks: pub.clocks, fonts: pub.fonts }[kind];
  const meta = list?.find((m) => m.id === id);
  const box = document.createElement('div');
  box.className = 'showcase';
  box.id = 'showcase';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-labelledby', 'scTitle');
  const head = `<div class="schead"><h2 id="scTitle">${esc(meta ? pick(meta.name, lang) : id || '?')}</h2>
    <span class="mute">${esc(kind || '')}${id ? ` · ${esc(id)}` : ''}${meta?.source === 'user' ? ` · ${esc(t('showcase.yours'))}` : ''}</span>
    <span class="sp"></span><button class="chipbtn" type="button" id="scClose">${esc(t('set.close'))}</button></div>`;
  if (kind === 'widgets') {
    box.innerHTML = `${head}<p class="lead">${esc(t('showcase.widgets'))}</p>`;
  } else if (!meta) {
    box.innerHTML = `${head}<p class="bad">${esc(t('showcase.missing', { kind: kind || '?', id: id || '?' }))}</p>`;
  } else {
    if (kind === 'fonts') F.load(id);
    const cols = columns(kind, id, pub);
    const rowName = (f) => `${t('showcase.tod_' + f.tod)} · ${t('wx.' + f.wx)}${f.mode === 'dash' ? ` · ${t('showcase.dash')}` : ''}`;
    box.innerHTML = `${head}<div class="scgrid" style="--cols:${cols.length}">
      <span></span>${cols.map((c) => `<b class="sccol">${esc(c.label)}</b>`).join('')}
      ${FRAMES.map((f, i) => `<b class="scrow">${esc(rowName(f))}</b>${cols.map((c) => `<div class="sccell" data-frame="${i}">${BG.mini(c.look, F.css(c.look.fonts))}</div>`).join('')}`).join('')}
    </div>`;
  }
  document.body.appendChild(box);
  BG.prepare(box, locale());
  box.querySelectorAll('.sccell').forEach((cell) => {
    const f = FRAMES[+cell.dataset.frame];
    const scrn = cell.querySelector('.scrn');
    BG.frame(scrn, f);
    if (['rain', 'thunder', 'snow'].includes(f.wx)) BG.play(scrn);
  });
  // clocks keep time (and pick up a changed clock design at once)
  clockTimer = setInterval(() => box.querySelectorAll('.scrn').forEach((s) => clocks.paint(s.querySelector('.ck'), s.dataset.clockId, new Date(), locale())), 1000);
  $('#scClose').onclick = close;
  $('#scClose').focus();
  addEventListener('keydown', function esc(e) {
    if (e.key !== 'Escape' || !$('#showcase')) return;
    e.stopImmediatePropagation();
    removeEventListener('keydown', esc, true);
    close();
  }, true);
}
