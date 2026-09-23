// Sends the screen's own errors to the backend journal (/api/client-log → Settings → About).
// Catches uncaught errors and rejected promises; other modules call report() for errors they
// handle themselves (a widget that failed, a server error). The same message is sent at most
// once a minute, and at most 20 reports a minute overall, so a broken loop can't flood it.

import { SEAT } from './api.js';

const seen = new Map();
let windowStart = 0, sent = 0;

export function report(kind, msg, stack = '', where = '') {
  msg = String(msg || '').slice(0, 500);
  if (!msg) return;
  const now = Date.now();
  const key = kind + '|' + msg;
  if (now - (seen.get(key) || 0) < 60000) return;
  seen.set(key, now);
  if (now - windowStart > 60000) { windowStart = now; sent = 0; }
  if (++sent > 20) return;
  const body = JSON.stringify({ kind, msg, stack: String(stack || '').slice(0, 4000), where: where || location.pathname + location.search });
  // keepalive: the report survives the page reloading right after an error
  fetch('/api/client-log?seat=' + encodeURIComponent(SEAT), {
    method: 'POST', keepalive: true, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Seat': SEAT }, body,
  }).catch(() => {});
}

export function init() {
  addEventListener('error', (e) => {
    // resource errors (a missing icon) carry no message and are expected: skip them
    if (!e.message) return;
    report('js', e.message, e.error?.stack || '', `${(e.filename || '').replace(location.origin, '')}:${e.lineno}:${e.colno}`);
  });
  addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    // a 401 after the session ended is handled by the app itself
    if (r?.status === 401) return;
    report('promise', r?.message || String(r), r?.stack || '');
  });
}
