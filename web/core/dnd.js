// Reordering systems and services: drag with the mouse, Alt+arrows with the keyboard.
// The order is the user's own (saved in their settings) and switches sorting to "manual".
import { api } from './api.js';
import { st } from './state.js';
import { moved } from './order.js';
import { $, $$, toast, keepFocus } from './ui.js';

let ctx = null; // { renderSystems, renderServices } from app.js

export async function saveOrder(kind, keys) {
  if (!keys) return;
  st.prefs.order = { ...(st.prefs.order || {}), [kind]: keys };
  st.prefs.sort = { ...(st.prefs.sort || {}), [kind]: 'manual' };
  const body = $('.scr-dash .body');
  keepFocus(body, kind === 'systems' ? ctx.renderSystems : ctx.renderServices);
  try { await api.put('/api/prefs', st.prefs); } catch (e) { toast(e.message, true); }
}

const listOf = (kind) => (kind === 'systems' ? st.systems : st.services);

export function init(c) {
  ctx = c;
  let dragKey = null, dragKind = null;
  addEventListener('dragstart', (e) => {
    const el = e.target.closest?.('[data-drag]');
    if (!el) return;
    dragKey = el.dataset.key; dragKind = el.dataset.drag;
    el.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragKey);
  });
  addEventListener('dragover', (e) => {
    const el = e.target.closest?.('[data-drag]');
    if (!el || el.dataset.drag !== dragKind) return;
    e.preventDefault();
    $$('.drop-before').forEach((x) => x !== el && x.classList.remove('drop-before'));
    el.classList.add('drop-before');
  });
  addEventListener('drop', (e) => {
    const el = e.target.closest?.('[data-drag]');
    if (!el || el.dataset.drag !== dragKind) return;
    e.preventDefault();
    if (el.dataset.key !== dragKey) saveOrder(dragKind, moved(dragKind, listOf(dragKind), st.prefs, dragKey, { beforeKey: el.dataset.key }));
  });
  addEventListener('dragend', () => {
    $$('.dragging, .drop-before').forEach((x) => x.classList.remove('dragging', 'drop-before'));
    dragKey = dragKind = null;
  });
  addEventListener('keydown', (e) => {
    if (st.screen !== 'dash' || !e.altKey || e.ctrlKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    const el = document.activeElement?.closest?.('[data-move]');
    if (!el || st.filter) return;
    e.preventDefault();
    const delta = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1;
    saveOrder(el.dataset.move, moved(el.dataset.move, listOf(el.dataset.move), st.prefs, el.dataset.key, { delta }));
  });
}
