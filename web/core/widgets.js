// Widget loader. A widget is web/widgets/<id>/widget.js (yours: /etc/pve-homelab/widgets/<id>/)
// exporting:
//   { zones: ['login','side'], public?: true | 'local', needs?: '<feature>', source?: '/api/..' | (ctx) => Promise,
//     every?: seconds, render(data, ctx) -> html, after?(el, data, ctx),
//     options?: [ { key, type, label, default, ... } ] }
// Its strings live next to it, one file per language: <id>/i18n/en.json, <id>/i18n/uk.json …
// ({"title": "…", …}; the backend serves them all at /widgets/i18n.json). An `i18n: {en: {…}}`
// block in the module still works; the files win.
// Inside render, ctx.t('key') reads the widget's own strings first, then the global dictionary,
// and ctx.opts holds the user's options merged over the defaults.
// `public` widgets may appear on the login screen (before anyone has logged in); 'local' ones
// only where host figures may be shown before sign-in (see allowed).
// How a widget looks is a design, not part of the widget: designs/widgets/<id>.css (or your own
// in /etc/pve-homelab/designs/widgets/<id>.css), loaded when it exists.
//
// Option types (label/hint/choice labels are keys of the widget's own strings):
//   toggle                         → true/false
//   select   choices: [[v, key]]   → one of the values
//   number   min, max, step        → a number
//   text     placeholder           → a line of text
//   date                           → 'YYYY-MM-DD'
//   list     placeholder           → text, one item per line (ctx.opts[key] is an array of lines)
//   checks   choices: [[v, key]]   → an array of the ticked values

import { api } from './api.js';
import * as ui from './ui.js';
import { extend, t } from './i18n.js';
import { report } from './errlog.js';

const wt = (id) => (key, vars) => {
  const own = t(`w.${id}.${key}`, vars);
  return own === `w.${id}.${key}` ? t(key, vars) : own;
};

const registry = {};
const timers = {};

// `styles`: the widgets that have a look in the designs folders (designs/widgets/<id>.css).
export async function load(ids, styles = []) {
  const strings = await api.get('/widgets/i18n.json').catch((e) => {
    report('widget', `strings: ${e.message}`, e.stack);
    return {};
  });
  await Promise.all(ids.map(async (id) => {
    try {
      const mod = (await import(`/widgets/${id}/widget.js`)).default;
      extend(`w.${id}.`, mod.i18n);
      extend(`w.${id}.`, strings[id]);
      registry[id] = { id, zones: ['side'], options: [], ...mod, t: wt(id), get title() { return wt(id)('title'); } };
      if (styles.includes(id)) {
        const l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = `/widgets/${id}/widget.css`;
        document.head.appendChild(l);
      }
    } catch (e) {
      console.warn('widget', id, e);
      report('widget', `${id}: ${e.message}`, e.stack);
    }
  }));
}

export const all = () => registry;

// public: true  -> may show on the sign-in screen anywhere;
// public: 'local' -> only where the sign-in screen may show host figures (the screens on the host,
//                    or web.sign_in: full for a browser elsewhere), which /api/public says as `stats`.
let hostFigures = true;
export function setHostFigures(on) { hostFigures = on !== false; }
// needs: 'weather' | 'wol' | ...: a widget of a part of the menu switched off on this host is not offered.
let featureOff = new Set();
export function setFeatures(f) { featureOff = new Set(Object.entries(f || {}).filter(([, on]) => on === false).map(([k]) => k)); }

export function allowed(zone) {
  return Object.values(registry).filter((w) => w.zones.includes(zone) && !featureOff.has(w.needs)
    && (zone !== 'login' || w.public === true || (w.public === 'local' && hostFigures)));
}

// The user's options for widget `id` over its defaults ("list" options become arrays of lines).
export function optionsOf(id, stored = {}) {
  const w = registry[id];
  const out = {};
  for (const o of w?.options || []) {
    const v = stored?.[o.key] ?? o.default;
    out[o.key] = o.type === 'list' ? String(v ?? '').split('\n').map((x) => x.trim()).filter(Boolean) : v;
  }
  return out;
}

// Several widgets may read the same endpoint (host and network both read /api/host):
// requests made close together share one answer instead of each hitting the backend.
// The top bar reads some of them too (/api/node-updates): `source` and `prime` below.
const shared = new Map(); // path -> { at, value } | { pending }
const readers = new Map(); // path -> Set of refresh functions of the widgets mounted on it
export function source(path, maxAgeMs) { return fetchShared(path, maxAgeMs); }
// A fresher answer for `path` came from elsewhere (the top bar's "Check now"): the widgets that read it show it now.
export function prime(path, value) {
  shared.set(path, { at: Date.now(), value });
  readers.get(path)?.forEach((r) => r());
}
function fetchShared(path, maxAgeMs) {
  const e = shared.get(path);
  if (e?.pending) return e.pending;
  if (e && Date.now() - e.at < maxAgeMs) return Promise.resolve(e.value);
  const pending = api.get(path)
    .then((value) => { shared.set(path, { at: Date.now(), value }); return value; })
    .catch((err) => { shared.delete(path); throw err; });
  shared.set(path, { pending });
  return pending;
}

// Nobody is looking at the widgets behind the screensaver or a VM's screen.
const hiddenNow = () => document.hidden || document.body.classList.contains('saver') || document.body.classList.contains('console');

// Render widget `id` into `box` and keep it fresh. Returns a stop function.
export function mount(box, id, zone, ctx) {
  const w = registry[id];
  box.className = 'glass w';
  box.dataset.w = id;
  const wctx = { ...ctx, zone, ui, t: w.t, opts: optionsOf(id, ctx.opts?.[id]) };
  const every = typeof w.every === 'function' ? w.every(wctx) : w.every;
  if (w.source) box.innerHTML = `<h4>${ui.esc(w.title)}</h4><div class="wload" role="progressbar" aria-label="${ui.esc(ui.t('widget.loading'))}"></div>`;
  const refresh = async (periodic = false) => {
    if (periodic && hiddenNow()) return;
    try {
      const data = !w.source ? null
        : typeof w.source === 'function' ? await w.source(wctx)
        : await fetchShared(w.source, every ? every * 500 : 1000);
      if (!box.isConnected && box._mounted) return;
      box._mounted = true;
      box.innerHTML = w.render(data, wctx);
      w.after?.(box, data, wctx);
    } catch (e) {
      box.innerHTML = `<h4>${ui.esc(w.title)}</h4><div class="werr">${ui.esc(e.message)}</div>
        <button type="button" class="wretry">${ui.esc(ui.t('widget.retry'))}</button>`;
      box.querySelector('.wretry').onclick = () => refresh();
      // the backend already logged its own failures, and a lost connection is no fault of the
      // widget (the offline banner shows it): record what broke in the browser
      if (!e.status && !e.offline) report('widget', `${id} (${zone}): ${e.message}`, e.stack);
    }
  };
  refresh();
  const timer = every ? setInterval(() => refresh(true), every * 1000) : null;
  const path = typeof w.source === 'string' ? w.source : null;
  if (path) { if (!readers.has(path)) readers.set(path, new Set()); readers.get(path).add(refresh); }
  return () => { clearInterval(timer); if (path) readers.get(path).delete(refresh); };
}

export function renderZone(zone, ids, ctx) {
  const el = ui.$(`[data-zone="${zone}"]`);
  (timers[zone] || []).forEach((stop) => stop());
  timers[zone] = [];
  el.innerHTML = '';
  for (const id of ids) {
    const w = registry[id];
    if (!w || !allowed(zone).includes(w)) continue;
    const box = document.createElement('div');
    box.style.setProperty('--i', el.children.length + 1);
    el.appendChild(box);
    timers[zone].push(mount(box, id, zone, ctx));
  }
}

export function stopZone(zone) {
  (timers[zone] || []).forEach((stop) => stop());
  timers[zone] = [];
}
