// Widget loader. A widget is web/widgets/<id>/widget.js exporting:
//   { title, zones: ['login','side'], public?: true, source?: '/api/..' | (ctx) => Promise,
//     every?: seconds, css?: true, render(data, ctx) -> html, after?(el, data, ctx) }
// `public` widgets may appear on the login screen (before anyone has logged in).

import { api } from './api.js';
import * as ui from './ui.js';

const registry = {};
const timers = {};

export async function load(ids) {
  await Promise.all(ids.map(async (id) => {
    try {
      const mod = (await import(`/widgets/${id}/widget.js`)).default;
      registry[id] = { id, zones: ['side'], ...mod };
      if (mod.css) {
        const l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = `/widgets/${id}/widget.css`;
        document.head.appendChild(l);
      }
    } catch (e) {
      console.warn('widget', id, e);
    }
  }));
}

export const all = () => registry;

export function allowed(zone) {
  return Object.values(registry).filter((w) => w.zones.includes(zone) && (zone !== 'login' || w.public));
}

export function renderZone(zone, ids, ctx) {
  const el = ui.$(`[data-zone="${zone}"]`);
  (timers[zone] || []).forEach(clearInterval);
  timers[zone] = [];
  el.innerHTML = '';
  for (const id of ids) {
    const w = registry[id];
    if (!w || !allowed(zone).includes(w)) continue;
    const box = document.createElement('div');
    box.className = 'glass w';
    box.dataset.w = id;
    box.style.setProperty('--i', el.children.length + 1);
    el.appendChild(box);
    const wctx = { ...ctx, zone, ui };
    const refresh = async () => {
      try {
        const data = w.source ? await (typeof w.source === 'function' ? w.source(wctx) : api.get(w.source)) : null;
        box.innerHTML = w.render(data, wctx);
        w.after?.(box, data, wctx);
      } catch (e) {
        box.innerHTML = `<h4>${ui.esc(w.title)}</h4><div class="werr">${ui.esc(e.message)}</div>`;
      }
    };
    refresh();
    if (w.every) timers[zone].push(setInterval(refresh, w.every * 1000));
  }
}

export function stopZone(zone) {
  (timers[zone] || []).forEach(clearInterval);
  timers[zone] = [];
}
