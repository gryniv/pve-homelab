// Proxmox package updates in the top bar, for those who may update the node (GET /api/node-updates):
// a button with how many packages wait, and a dialog that lists them, checks again on request
// (POST /api/node-updates/refresh) and points to where they are installed: Proxmox itself.
// The answer is shared with the "Proxmox updates" widget (widgets.source / prime).
import { api } from './api.js';
import * as W from './widgets.js';
import { $, esc, fmt, icon, t, toast } from './ui.js';

const PATH = '/api/node-updates';
let data = null, ctx = null, busy = false, opener = null;

const btn = () => $('#nodeUpd');
const layer = () => $('#nodeUpdLayer');
const wanted = () => ctx?.prefs()?.top?.pve_updates !== false;

// May this person update the node (and so see the list)? Known after the first check.
export const allowed = () => !!data?.allowed;

export async function check() {
  try { data = await W.source(PATH, 5 * 60000); } catch { return; }
  paint();
}

export function paint() {
  const b = btn();
  const on = !!(data?.allowed && data.count && wanted());
  b.hidden = !on;
  if (on) {
    b.classList.toggle('kern', !!data.kernel);
    b.querySelector('.n').textContent = data.count;
    const label = t('nodeupd.button', { n: data.count }) + (data.kernel ? ` · ${t('nodeupd.kernel_short')}` : '');
    b.setAttribute('aria-label', label);
    b.title = label;
  }
  if (!layer().hidden) paintDialog();
}

// Signed out: nothing of the previous user's stays on screen.
export function reset() {
  data = null;
  btn().hidden = true;
  layer().hidden = true;
}

function paintDialog() {
  const d = data || { count: 0, packages: [] };
  const ago = d.checked ? t('nodeupd.checked', { ago: fmt.ago(Math.max(60, Date.now() / 1000 - d.checked)) }) : '';
  const sub = [d.proxmox ? t('nodeupd.from_pve', { n: d.proxmox }) : '', ago].filter(Boolean).join(' · ');
  const rest = d.count - d.packages.length;
  $('#nodeUpdBody').innerHTML = !d.count
    ? `<div class="nusum none"><span class="dot ok"></span><span>${esc(t('nodeupd.none'))}${ago ? `<small class="mute">${esc(ago)}</small>` : ''}</span></div>`
    : `<div class="nusum"><b>${d.count}</b><span>${esc(t('nodeupd.waiting', { n: d.count }))}${sub ? `<small class="mute">${esc(sub)}</small>` : ''}</span></div>
      ${d.kernel ? `<div class="nukern">${icon('i-restart')}<span>${esc(t('nodeupd.kernel'))}</span></div>` : ''}
      <ul class="pkglist">${d.packages.map((p) => `<li${p.origin === 'Proxmox' ? ' class="pve"' : ''}><span class="nm">${esc(p.name)}</span>
        <small class="mute">${p.old ? `${esc(p.old)} → ` : `${esc(t('nodeupd.new_pkg'))} `}${esc(p.new)}</small></li>`).join('')}
        ${rest > 0 ? `<li class="more mute">${esc(t('nodeupd.more', { n: rest }))}</li>` : ''}</ul>
      <p class="lead nuhow">${esc(t('nodeupd.how'))}</p>`;
  const c = $('#nuCheck');
  c.disabled = busy;
  c.setAttribute('aria-busy', String(busy));
  c.querySelector('span').textContent = t(busy ? 'nodeupd.checking' : 'nodeupd.check');
}

async function checkNow() {
  if (busy) return;
  busy = true;
  paintDialog();
  try {
    data = await api.post(PATH + '/refresh');
    W.prime(PATH, data);
    toast(data.count ? t('nodeupd.checked_n', { n: data.count }) : t('nodeupd.checked_none'));
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy = false;
    paint();
    if (!layer().hidden) $('#nuCheck').focus();
  }
}

export async function show(from) {
  if (!data) await check();
  if (!data?.allowed) return;
  opener = from || btn();
  layer().hidden = false;
  paintDialog();
  $('#nuClose').focus();
}

function hide() {
  layer().hidden = true;
  // the button may be gone by now (everything got installed): the settings button is next to it
  (opener && !opener.hidden && opener.isConnected ? opener : $('.scr-dash .top .me'))?.focus();
}

// `app`: the facade from app.js (prefs, openUrl, pveUrl).
export function init(app) {
  ctx = app;
  btn().onclick = (e) => show(e.currentTarget);
  $('#nuCheck').onclick = checkNow;
  $('#nuOpen').onclick = () => {
    hide();
    Promise.resolve(app.openUrl(app.pveUrl())).catch((e) => toast(e.message, true));
  };
  $('#nuClose').onclick = hide;
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !layer().hidden) { e.stopImmediatePropagation(); e.preventDefault(); hide(); }
  }, true);
}
