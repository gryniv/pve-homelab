// Live reload while designing (the demo, or `designer: true` on a host): when a design file
// changes, its stylesheet or clock is swapped in place, no reload; when a design is added or
// removed, the page reloads to pick up the new lists. The backend side is /api/designs/events.
import * as clocks from './clocks.js';
import { toast, t } from './ui.js';

const HREF = {
  themes: (id) => `/themes/${id}.css`,
  backgrounds: (id) => `/backgrounds/${id}.css`,
  fonts: (id) => `/fonts/${id}.css`,
  widgets: (id) => `/widgets/${id}/widget.css`,
};

function swap(kind, id, stamp) {
  if (kind === 'clocks') { clocks.reload(id); return; }
  const href = HREF[kind]?.(id);
  if (!href) return;
  document.querySelectorAll('link[rel="stylesheet"]').forEach((l) => {
    if ((l.getAttribute('href') || '').split('?')[0] === href) l.href = `${href}?v=${stamp}`;
  });
}

export function init(pub) {
  if (!pub?.designer || !window.EventSource) return;
  const es = new EventSource('/api/designs/events');
  es.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (d.catalog) { location.reload(); return; }
    const stamp = Date.now();
    d.changed.forEach((c) => swap(c.kind, c.id, stamp));
    if (d.changed.length) toast(t('designer.updated', { what: d.changed.map((c) => c.id).join(', ') }));
  };
}
