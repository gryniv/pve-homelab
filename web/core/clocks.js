import { report } from './errlog.js';

// Clock designs are drop-in modules: designs/clocks/<id>.js (see README: "Add a clock").
// A module exports `css` (scoped by [data-clockk="<id>"]) and `render(el, date, ctx)`,
// which is called every second and should only touch what changed.

const loaded = {};
const version = {}; // id -> a stamp after the file changed (live reload), so import() fetches it again

export function load(id) {
  id = id || 'digital';
  return (loaded[id] ||= import(`/clocks/${id}.js${version[id] ? `?v=${version[id]}` : ''}`).then((m) => {
    document.getElementById('clock-css-' + id)?.remove();
    if (m.css) {
      const s = document.createElement('style');
      s.id = 'clock-css-' + id;
      s.textContent = m.css;
      document.head.appendChild(s);
    }
    return m;
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

const parts = (d, locale) => {
  const hm = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const [h, m] = hm.split(/[:.]/);
  return { h, m, s: String(d.getSeconds()).padStart(2, '0'), text: hm, date: d };
};

// Draw clock `id` into `el` (switching design if needed).
export async function paint(el, id, d, locale) {
  const m = await load(id);
  if (!m) return;
  if (el.dataset.clockk !== id) { el.dataset.clockk = id; el.innerHTML = ''; }
  m.render(el, parts(d, locale), { locale });
}
