// Clock designs are drop-in modules: web/clocks/<id>.js (see README: "Add a clock").
// A module exports `css` (scoped by [data-clockk="<id>"]) and `render(el, date, ctx)`,
// which is called every second and should only touch what changed.

const loaded = {};

export function load(id) {
  id = id || 'digital';
  return (loaded[id] ||= import(`/clocks/${id}.js`).then((m) => {
    if (m.css && !document.getElementById('clock-css-' + id)) {
      const s = document.createElement('style');
      s.id = 'clock-css-' + id;
      s.textContent = m.css;
      document.head.appendChild(s);
    }
    return m;
  }).catch(() => (id === 'digital' ? null : load('digital'))));
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
