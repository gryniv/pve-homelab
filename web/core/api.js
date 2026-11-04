// Thin wrapper over the backend. The seat id and UI language travel with every request.
import { current as lang, t } from './i18n.js';
import { report } from './errlog.js';

// The kiosk names its seat in the URL; a browser elsewhere is the "web" seat. The backend decides
// either way and /api/public says which (setSeat), so a page elsewhere can't pass for a monitor.
export let SEAT = new URLSearchParams(location.search).get('seat') || '';
export function setSeat(id) { SEAT = id || SEAT; }

// The kiosk has no reload button: if the backend goes away (update, restart), wait for it and reload.
let waiting = false;
async function backendLost() {
  if (waiting) return;
  waiting = true;
  const banner = document.getElementById('offline');
  if (banner) banner.hidden = false;
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    try { if ((await fetch('/api/health', { cache: 'no-store' })).ok) return location.reload(); } catch {}
  }
}

async function call(method, path, body) {
  let r;
  // FormData (files) goes as multipart, with the browser's own Content-Type and boundary
  const form = body instanceof FormData;
  try {
    r = await fetch(path, {
      method,
      headers: form ? { 'X-Seat': SEAT, 'X-Lang': lang() } : { 'Content-Type': 'application/json', 'X-Seat': SEAT, 'X-Lang': lang() },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (e) {
    backendLost();
    // not a fault to record: the banner says it, and a request cut by the page reloading lands here too
    const lost = new Error(t('error.backend'));
    lost.offline = true;
    throw lost;
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

const withSeat = (p) => (SEAT ? p + (p.includes('?') ? '&' : '?') + 'seat=' + encodeURIComponent(SEAT) : p);

export const api = {
  get: (p) => call('GET', withSeat(p)),
  post: (p, b = {}) => call('POST', withSeat(p), b),
  put: (p, b) => call('PUT', withSeat(p), b),
  del: (p) => call('DELETE', withSeat(p)),
};
