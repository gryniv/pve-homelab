// New versions from GitHub: the pill in the top bar, the reminder after sign-in, the install
// button for admins, and a word about a failed update (see backend/pvehomelab/update.py).
import { api } from './api.js';
import { $, t, toast, confirmBox } from './ui.js';

let upd = null, reminded = false;

export const status = () => upd;
export const label = (u) => (u.latest.version ? `v${u.latest.version}` : (u.latest.commit || '').slice(0, 7));

// Called after every sign-in: the reminder is once per sign-in.
export function resetReminder() { reminded = false; }

export async function check() {
  try { upd = await api.get('/api/update'); } catch { upd = null; }
  reportLast(upd);
  paint();
  if (upd?.available && !reminded) { reminded = true; toast(t('upd.remind', { v: label(upd) })); }
}

// The pill's text follows the language.
export function paint() {
  const pill = $('#updPill');
  pill.hidden = !upd?.available;
  if (!upd?.available) return;
  pill.querySelector('span').textContent = t('upd.pill', { v: label(upd) });
  pill.title = upd.latest.notes || '';
}

// A failed update (kept or rolled back) is told to admins once, on the seat they sign in at.
function reportLast(u) {
  const r = u?.last;
  if (!r || r.ok || !u.can_apply) return;
  const key = `pvehomelab.updfail.${r.time}`;
  try { if (localStorage.getItem(key)) return; localStorage.setItem(key, '1'); } catch {}
  toast(t(r.rolled_back ? 'upd.failed_back' : 'upd.failed', { v: r.ref, err: r.error }), true);
}

export function init() {
  $('#updPill').onclick = async () => {
    if (!upd?.available) return;
    const v = label(upd);
    if (!upd.can_apply) { toast(t('upd.no_perm', { v }), true); return; }
    if (!(await confirmBox(t('upd.confirm_title', { v }), t('upd.confirm_text'), t('upd.apply')))) return;
    try { await api.post('/api/update/apply'); toast(t('upd.started')); $('#updPill').hidden = true; }
    catch (e) { toast(e.message, true); }
  };
}
