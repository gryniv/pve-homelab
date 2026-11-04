// Write to the author (Settings → About): a GitHub issue composed here, shown in full before
// anything leaves the host, and finished on GitHub: from a phone through the QR code, or in a tab.
// The backend composes it (/api/feedback) and takes names and addresses out of the error journal.
import { api } from './api.js';
import * as tabs from './tabs.js';
import { $, $$, esc, icon, t, toast } from './ui.js';
import { current } from './i18n.js';

const KINDS = ['bug', 'idea', 'question'];
let form = { kind: 'bug', title: '', text: '', env: true, journal: false };
let last = null, timer = null, seq = 0, opener = null;

const layer = () => $('#feedbackLayer');

function shell() {
  const sw = (id, on, title, sub) => `<label class="tgl"><span>${esc(t(title))}${sub ? `<small>${esc(t(sub))}</small>` : ''}</span>
    <span class="sw"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><i></i></span></label>`;
  return `<h3 id="fbTitle">${esc(t('fb.title'))}</h3>
    <p class="lead">${esc(t('fb.lead'))}</p>
    <div class="fbgrid">
      <div class="fbform">
        <div class="seg" id="fbKind" role="group" aria-label="${esc(t('fb.kind'))}">${KINDS.map((k) =>
          `<button type="button" data-v="${k}" aria-pressed="${form.kind === k}">${esc(t('fb.k_' + k))}</button>`).join('')}</div>
        <div class="fld"><label for="fbSubject">${esc(t('fb.subject'))}</label>
          <input id="fbSubject" maxlength="120" value="${esc(form.title)}" placeholder="${esc(t('fb.subject_ph'))}"></div>
        <div class="fld"><label for="fbText">${esc(t('fb.text'))}</label>
          <textarea id="fbText" rows="5" maxlength="4000" placeholder="${esc(t('fb.text_ph'))}">${esc(form.text)}</textarea></div>
        ${sw('fbEnv', form.env, 'fb.env', 'fb.env_sub')}
        <div id="fbJournalRow">${sw('fbJournal', form.journal, 'fb.journal', 'fb.journal_sub')}</div>
      </div>
      <div class="fbside">
        <div class="fbqr" id="fbQr" role="img" aria-label="${esc(t('fb.qr_aria'))}"></div>
        <p class="mute fbnote" id="fbQrNote" aria-live="polite"></p>
        <button class="btn" type="button" id="fbOpen" disabled>${icon('i-ext')}<span>${esc(t('fb.open'))}</span></button>
      </div>
    </div>
    <details class="fbprev"><summary>${esc(t('fb.preview'))}</summary><pre id="fbBody"></pre></details>
    <div class="mbtns"><button class="btn ghost" type="button" id="fbClose">${esc(t('set.close'))}</button></div>`;
}

function paint() {
  const d = last;
  if (!d) return;
  $('#fbQr').innerHTML = d.qr || '';
  $('#fbQr').hidden = !d.qr;
  $('#fbQrNote').textContent = d.too_long ? t('fb.too_long') : d.qr ? t('fb.scan') : t('fb.no_qr');
  $('#fbOpen').disabled = !d.url;
  $('#fbBody').textContent = `${d.title}\n\n${d.body}`;
  $('#fbJournalRow').hidden = !d.journal_allowed;
  if (form.journal && d.journal_total > d.journal_shown) $('#fbQrNote').textContent += ` ${t('fb.journal_cut', { n: d.journal_shown, total: d.journal_total })}`;
}

async function refresh() {
  const mine = ++seq;
  const client = { ua: navigator.userAgent, screen: `${screen.width}x${screen.height}`, lang: current() };
  try {
    const d = await api.post('/api/feedback', { ...form, client });
    if (mine !== seq || layer().hidden) return; // a newer one is on its way, or the dialog closed
    last = d;
    paint();
  } catch (e) {
    if (mine === seq) $('#fbQrNote').textContent = e.message;
  }
}

const later = () => { clearTimeout(timer); timer = setTimeout(refresh, 350); };

// `from`: where focus goes back to when the dialog closes (the button that opened it).
export function show(from) {
  opener = from || document.activeElement;
  const box = $('#fbBox');
  box.innerHTML = shell();
  layer().hidden = false;
  $$('#fbKind button').forEach((b) => (b.onclick = () => {
    form.kind = b.dataset.v;
    $$('#fbKind button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    refresh();
  }));
  $('#fbSubject').oninput = (e) => { form.title = e.target.value; later(); };
  $('#fbText').oninput = (e) => { form.text = e.target.value; later(); };
  $('#fbEnv').onchange = (e) => { form.env = e.target.checked; refresh(); };
  $('#fbJournal').onchange = (e) => { form.journal = e.target.checked; refresh(); };
  $('#fbOpen').onclick = () => {
    if (!last?.url) return;
    tabs.open(last.url).catch((e) => toast(e.message, true));
  };
  $('#fbClose').onclick = hide;
  $('#fbJournalRow').hidden = true; // until the backend says this person may add it
  refresh();
  $('#fbSubject').focus();
}

export function hide() {
  clearTimeout(timer);
  layer().hidden = true;
  $('#fbBox').innerHTML = '';
  opener?.focus?.();
}

export function init() {
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !layer().hidden) { e.stopImmediatePropagation(); e.preventDefault(); hide(); }
  }, true);
}
