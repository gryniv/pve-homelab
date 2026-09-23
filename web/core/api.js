// Thin wrapper over the backend. The seat id and UI language travel with every request.
import { current as lang, t } from './i18n.js';
import { report } from './errlog.js';

export const SEAT = new URLSearchParams(location.search).get('seat') || 'igpu';

// The kiosk has no reload button: if the backend goes away (update, restart), wait for it and reload.
let waiting = false;
async function backendLost() {
  if (waiting) return;
  waiting = true;
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    try { if ((await fetch('/api/host?seat=' + SEAT, { cache: 'no-store' })).ok) return location.reload(); } catch {}
  }
}

async function call(method, path, body) {
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Seat': SEAT, 'X-Lang': lang() },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (e) {
    backendLost();
    throw new Error(t('error.backend'));
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(data.error || `Error ${r.status}`);
    e.status = r.status;
    // 4xx are answers for the user (wrong password, no rights); 5xx are faults worth a record
    if (r.status >= 500) report('api', `${method} ${path.split('?')[0]} → ${r.status}: ${e.message}`);
    throw e;
  }
  return data;
}

const withSeat = (p) => p + (p.includes('?') ? '&' : '?') + 'seat=' + encodeURIComponent(SEAT);

export const api = {
  get: (p) => call('GET', withSeat(p)),
  post: (p, b = {}) => call('POST', withSeat(p), b),
  put: (p, b) => call('PUT', withSeat(p), b),
  del: (p) => call('DELETE', withSeat(p)),
};
