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
const KEYS = ['id', 'data-sys', 'data-url', 'data-act', 'data-console', 'data-sp', 'data-skin', 'data-v', 'data-av',
  'data-add', 'data-mv', 'data-rm', 'data-hide', 'data-gpu', 'data-ptab', 'data-user', 'data-q', 'data-tab', 'data-tabx'];
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

let toastTimer;
export function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('bad', bad);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), bad ? 6000 : 3000);
}

export function confirmBox(title, text, yes) {
  return new Promise((resolve) => {
    $('#cTitle').textContent = title;
    $('#cText').textContent = text;
    $('#cYes').textContent = yes;
    const layer = $('#confirmLayer');
    layer.hidden = false;
    const done = (v) => { layer.hidden = true; $('#cYes').onclick = $('#cNo').onclick = null; resolve(v); };
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
