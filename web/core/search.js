// Search on the dashboard: just start typing, the key lands in the search box and the
// web services narrow down (on the Containers & VMs tab: the guests' filter). Esc clears it,
// Enter opens the first match.
import { st } from './state.js';
import * as nav from './nav.js';
import { $, $$ } from './ui.js';

let ctx = null; // { renderServices } from app.js

export function setFilter(v) {
  st.filter = v;
  const box = $('#svcSearch');
  box.hidden = !v;
  if (box.value !== v) box.value = v;
  if (v) $$('[data-ptab]').forEach((x) => x.setAttribute('aria-selected', x.dataset.ptab === 'web')), $$('[data-pane]').forEach((p) => (p.hidden = p.dataset.pane !== 'web'));
  ctx.renderServices();
}

export function init(c) {
  ctx = c;
  $('#svcSearch').addEventListener('input', (e) => setFilter(e.target.value));
  $('#svcSearch').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); setFilter(''); nav.focusFirst(undefined, '#svcgrid .svc'); }
    if (e.key === 'Enter') { const first = $('#svcgrid .svc'); if (first) first.click(); }
  });
  addEventListener('keydown', (e) => {
    if (st.screen !== 'dash' || e.ctrlKey || e.altKey || e.metaKey || e.key.length !== 1 || e.key === ' ' || e.key === '?') return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
    // On the Containers & VMs tab the letters filter the guests instead.
    if (!$('[data-pane=guests]').hidden) { $('#guestFilter').focus(); return; }
    const box = $('#svcSearch');
    box.hidden = false;
    box.focus(); // the key lands in the search box
  }, true);
}
