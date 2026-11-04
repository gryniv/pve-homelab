// The bell in the top bar: what needs a look (GET /api/alerts), and the dialog that lists it.
import { api } from './api.js';
import { $, t, esc } from './ui.js';

let items = [];

const text = (a) => {
  if (a.kind === 'backup') return t(a.never ? 'alerts.backup_never' : 'alerts.backup', a);
  if (a.kind === 'service' && a.guest) return t('alerts.service_guest', a);
  return t('alerts.' + a.kind, a);
};

export async function check() {
  try { items = (await api.get('/api/alerts')).alerts; } catch { return; }
  const b = $('#alertBell');
  b.hidden = !items.length;
  b.classList.toggle('bad', items.some((a) => a.level === 'bad'));
  b.querySelector('.n').textContent = items.length;
  b.setAttribute('aria-label', `${t('alerts.title')}: ${items.length}`);
  if (!$('#alertsLayer').hidden) paint();
}

// Signed out: nothing of the previous user's stays on screen.
export function reset() {
  items = [];
  $('#alertBell').hidden = true;
  $('#alertsLayer').hidden = true;
}

function paint() {
  $('#alertsList').innerHTML = items.length
    ? items.map((a) => `<li class="${a.level}"><span class="dot ${a.level === 'bad' ? 'bad' : 'warn'}"></span><span>${esc(text(a))}</span></li>`).join('')
    : `<li class="none">${esc(t('alerts.none'))}</li>`;
}

function show() {
  paint();
  $('#alertsLayer').hidden = false;
  $('#alertsClose').focus();
}

function hide() {
  $('#alertsLayer').hidden = true;
  $('#alertBell').focus();
}

export function init() {
  $('#alertBell').onclick = show;
  $('#alertsClose').onclick = hide;
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#alertsLayer').hidden) { e.stopImmediatePropagation(); hide(); }
  }, true);
}
