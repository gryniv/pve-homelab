import { report } from './errlog.js';

// Clock designs are drop-in modules: designs/clocks/<id>.js (see README: "Add a clock").
// A module exports `css` (scoped by [data-clockk="<id>"]) and `render(el, date, ctx)`,
// which is called every second and should only touch what changed.

const loaded = {};
const version = {}; // id -> a stamp after the file changed (live reload), so import() fetches it again
let known = null;   // the clock designs this host has (/api/public); null until the page knows them

export function init(list) { known = new Set((list || []).map((c) => c.id)); }

// The module of clock `id` and the id it really is: a design removed since someone chose it is not
// a fault of the page, so the digital clock stands in, quietly; one that fails to load stands in too.
export function load(id) {
  id = id || 'digital';
  if (known && !known.has(id)) id = 'digital';
  return (loaded[id] ||= import(`/clocks/${id}.js${version[id] ? `?v=${version[id]}` : ''}`).then((m) => {
    document.getElementById('clock-css-' + id)?.remove();
    if (m.css) {
      const s = document.createElement('style');
      s.id = 'clock-css-' + id;
      s.textContent = m.css;
      document.head.appendChild(s);
    }
    return { m, id };
  }).catch((e) => {
    report('clock', `${id}: ${e.message}`, e.stack);
    return id === 'digital' ? null : load('digital');
  }));
}

// The design file changed: the next paint loads it afresh, and every clock in that design is
// drawn again from scratch.
export function reload(id) {
  version[id] = Date.now();
  delete loaded[id];
  document.querySelectorAll(`[data-clockk="${CSS.escape(id)}"]`).forEach((el) => { el.dataset.clockk = ''; });
}

// 24 or 12 hours (Settings → Interface)
let cycle = 'h23';
export function setHours(h) { cycle = h === '12' ? 'h12' : 'h23'; }

const parts = (d, locale) => {
  const hm = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hourCycle: cycle });
  const [h, m] = hm.replace(/\s*[^\d:.\s]+\.?\s*/g, '').split(/[:.]/);
  return { h, m, s: String(d.getSeconds()).padStart(2, '0'), text: hm, date: d };
};

// Draw clock `id` into `el` (switching design if needed).
// It is marked with the design it really shows, whose CSS is scoped by [data-clockk].
export async function paint(el, id, d, locale) {
  const got = await load(id);
  if (!got) return;
  if (el.dataset.clockk !== got.id) { el.dataset.clockk = got.id; el.innerHTML = ''; }
  got.m.render(el, parts(d, locale), { locale });
}
