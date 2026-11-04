// Small shared helpers used by the core and by widgets.
import { t, locale } from './i18n.js';

export { t, locale };

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const icon = (id, cls = 'i') => `<svg class="${cls}"><use href="#${id}"/></svg>`;
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const AVATARS = [
  'linear-gradient(135deg,#ff9a55,#d9480f)', 'linear-gradient(135deg,#5aa9ff,#2553b8)',
  'linear-gradient(135deg,#6be09a,#1f8a55)', 'linear-gradient(135deg,#d58cff,#6a3bc2)',
  'linear-gradient(135deg,#ff7aa2,#c2255c)', 'linear-gradient(135deg,#6b7684,#2c343d)',
];

export function avatar(user, idx) {
  const bg = AVATARS[(idx ?? 0) % AVATARS.length];
  const inner = user.id === 'root@pam' ? `<svg viewBox="0 0 24 24"><use href="#i-lock"/></svg>` : esc((user.name || user.id)[0].toUpperCase());
  return { bg, inner };
}

export const fmt = {
  bytes(n) {
    if (!n) return '0';
    const u = ['unit.b', 'unit.kb', 'unit.mb', 'unit.gb', 'unit.tb'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${t(u[i])}`;
  },
  gb: (n) => (n / 1024 ** 3).toFixed(n >= 10 * 1024 ** 3 ? 0 : 1),
  pct: (x) => `${Math.round(x)}%`,
  uptime(s) {
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    const [D, H, M] = [t('unit.d'), t('unit.h'), t('unit.min')];
    return d ? `${d} ${D} ${h} ${H}` : h ? `${h} ${H} ${m} ${M}` : `${m} ${M}`;
  },
  ago(s) {
    if (!s) return '';
    return fmt.uptime(s);
  },
};

// Re-render `root` via fn() without losing keyboard focus (matched by a stable attribute).
const KEYS = ['id', 'data-sys', 'data-url', 'data-act', 'data-console', 'data-sp', 'data-skinpick', 'data-bgk', 'data-clk', 'data-font', 'data-v', 'data-av',
  'data-add', 'data-mv', 'data-rm', 'data-hide', 'data-gpu', 'data-ptab', 'data-user', 'data-q', 'data-tab', 'data-tabx',
  'data-omv', 'data-vis', 'data-wcfg', 'data-wo', 'data-wochk', 'data-guest', 'data-sort', 'data-range'];
export function keepFocus(root, fn) {
  const a = document.activeElement;
  let sel = null;
  if (a && a !== document.body && root.contains(a)) {
    for (const k of KEYS) {
      const v = a.getAttribute(k);
      if (v !== null) { sel = k === 'id' ? '#' + CSS.escape(v) : `[${k}="${CSS.escape(v)}"]`; break; }
    }
  }
  fn();
  if (sel) root.querySelector(sel)?.focus();
}

// One message at a time; the next waits instead of overwriting it (a repeat is dropped).
const toastQueue = [];
let toastBusy = false;
let toastMs = 3000;
export function setToastTime(sec) { toastMs = Math.max(2, Math.min(15, Number(sec) || 3)) * 1000; }

export function toast(msg, bad = false) {
  if (toastQueue.some((x) => x.msg === msg) || ($('#toast').textContent === msg && toastBusy)) return;
  toastQueue.push({ msg, bad });
  if (!toastBusy) nextToast();
}
function nextToast() {
  const t = $('#toast');
  const m = toastQueue.shift();
  if (!m) { toastBusy = false; t.hidden = true; t.textContent = ''; return; }
  toastBusy = true;
  t.textContent = m.msg;
  t.classList.toggle('bad', m.bad);
  t.hidden = false;
  // a queued message shortens the current one, never below 1.5 s
  const ms = toastQueue.length ? 1500 : (m.bad ? toastMs * 2 : toastMs);
  setTimeout(nextToast, ms);
}

export function confirmBox(title, text, yes) {
  return new Promise((resolve) => {
    $('#cTitle').textContent = title;
    $('#cText').textContent = text;
    $('#cYes').textContent = yes;
    const layer = $('#confirmLayer');
    const back = document.activeElement;
    layer.hidden = false;
    // Esc answers "no" here and stops, so it does not also close the screen underneath.
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault(); e.stopImmediatePropagation();
      done(false);
    };
    const done = (v) => {
      layer.hidden = true;
      $('#cYes').onclick = $('#cNo').onclick = null;
      removeEventListener('keydown', onKey, true);
      if (back?.isConnected) back.focus();
      resolve(v);
    };
    addEventListener('keydown', onKey, true);
    $('#cYes').onclick = () => done(true);
    $('#cNo').onclick = () => done(false);
    $('#cNo').focus();
  });
}

// Weather icon for a weather kind (clear/partly/...) and day/night.
const WX_ICON = {
  clear: ['clear-day', 'clear-night'], partly: ['partly-cloudy-day', 'partly-cloudy-night'],
  overcast: ['overcast-day', 'overcast-night'], rain: ['rain', 'rain'], thunder: ['thunderstorms', 'thunderstorms'],
  snow: ['snow', 'snow'], fog: ['fog', 'fog'],
};
export const wxIcon = (kind, night) => `/assets/wx/${(WX_ICON[kind] || WX_ICON.partly)[night ? 1 : 0]}.svg`;

// "VM" / "CT" for a guest type as Proxmox names it (qemu / lxc); empty for anything else.
export const kindLabel = (type) => (type === 'qemu' ? 'VM' : type === 'lxc' ? 'CT' : '');
