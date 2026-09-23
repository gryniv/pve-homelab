// Widget loader. A widget is web/widgets/<id>/widget.js exporting:
//   { zones: ['login','side'], public?: true, source?: '/api/..' | (ctx) => Promise,
//     every?: seconds, css?: true, render(data, ctx) -> html, after?(el, data, ctx),
//     options?: [ { key, type, label, default, ... } ],
//     i18n: { uk: { title: '…', … }, en: { title: '…', … } } }
// Inside render, ctx.t('key') reads the widget's own strings first, then the global dictionary,
// and ctx.opts holds the user's options merged over the defaults.
// `public` widgets may appear on the login screen (before anyone has logged in).
//
// Option types (label/hint/choice labels are keys of the widget's own i18n):
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

export async function load(ids) {
  await Promise.all(ids.map(async (id) => {
    try {
      const mod = (await import(`/widgets/${id}/widget.js`)).default;
      extend(`w.${id}.`, mod.i18n);
      registry[id] = { id, zones: ['side'], options: [], ...mod, t: wt(id), get title() { return wt(id)('title'); } };
      if (mod.css) {
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

export function allowed(zone) {
  return Object.values(registry).filter((w) => w.zones.includes(zone) && (zone !== 'login' || w.public));
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

// Render widget `id` into `box` and keep it fresh. Returns a stop function.
export function mount(box, id, zone, ctx) {
  const w = registry[id];
  box.className = 'glass w';
  box.dataset.w = id;
  const wctx = { ...ctx, zone, ui, t: w.t, opts: optionsOf(id, ctx.opts?.[id]) };
  const refresh = async () => {
    try {
      const data = w.source ? await (typeof w.source === 'function' ? w.source(wctx) : api.get(w.source)) : null;
      if (!box.isConnected && box._mounted) return;
      box._mounted = true;
      box.innerHTML = w.render(data, wctx);
      w.after?.(box, data, wctx);
    } catch (e) {
      box.innerHTML = `<h4>${ui.esc(w.title)}</h4><div class="werr">${ui.esc(e.message)}</div>`;
      // the backend already logged its own failures; record what broke in the browser
      if (!e.status) report('widget', `${id} (${zone}): ${e.message}`, e.stack);
    }
  };
  refresh();
  const every = typeof w.every === 'function' ? w.every(wctx) : w.every;
  const timer = every ? setInterval(refresh, every * 1000) : null;
  return () => clearInterval(timer);
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
