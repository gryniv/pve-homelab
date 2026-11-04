// The "Containers & VMs" table: every guest the user may see, with load, start/stop/reboot,
// a console inside the menu, sorting by any column, a filter, and a guest's history
// (CPU, memory, network over the last hour, day or week) in a dialog.
import { api } from './api.js';
import { st } from './state.js';
import { lines, last, peak } from './chart.js';
import { $, $$, icon, esc, fmt, toast, confirmBox, t, kindLabel, locale } from './ui.js';

let ctx = null; // { openUrl, pveUrl, openConsole, refreshDash } from app.js

/* ---------------- sorting and filter ---------------- */
const SORT_KEY = 'pvehomelab.guestsort';
let sort = (() => { try { return JSON.parse(localStorage.getItem(SORT_KEY)) || { by: 'vmid', dir: 1 }; } catch { return { by: 'vmid', dir: 1 }; } })();
let filter = '';

const running = (g) => g.status === 'running';
const SORTERS = {
  name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
  vmid: (a, b) => a.vmid - b.vmid,
  type: (a, b) => a.type.localeCompare(b.type) || a.vmid - b.vmid,
  status: (a, b) => running(b) - running(a) || a.vmid - b.vmid,
  cpu: (a, b) => (running(a) ? a.cpu || 0 : -1) - (running(b) ? b.cpu || 0 : -1) || a.vmid - b.vmid,
  mem: (a, b) => (running(a) ? a.mem || 0 : -1) - (running(b) ? b.mem || 0 : -1) || a.vmid - b.vmid,
};

function visible() {
  const q = filter.trim().toLowerCase();
  const list = st.guests.filter((g) => !q || `${g.name} ${g.vmid} ${kindLabel(g.type)} ${t(running(g) ? 'guest.running' : 'guest.stopped')}`.toLowerCase().includes(q));
  const cmp = SORTERS[sort.by] || SORTERS.vmid;
  return list.sort((a, b) => cmp(a, b) * sort.dir);
}

function paintHeaders() {
  $$('[data-pane=guests] th[data-col]').forEach((th) => {
    const on = th.dataset.col === sort.by;
    if (on) th.setAttribute('aria-sort', sort.dir > 0 ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
  });
}

/* ---------------- the table ---------------- */
export function render() {
  $('#guestCount').textContent = st.guests.length;
  paintHeaders();
  const svcBy = {};
  st.services.forEach((s) => { if (s.guest) (svcBy[s.guest.vmid] ||= s); });
  const list = visible();
  if (!list.length) {
    $('#guestrows').innerHTML = `<tr><td colspan="8" class="mute">${esc(filter ? t('search.none', { q: filter }) : t('guest.none'))}</td></tr>`;
    return;
  }
  $('#guestrows').innerHTML = list.map((g) => {
    const run = running(g), svc = svcBy[g.vmid];
    const logo = svc ? `<img src="/icons/${esc(svc.icon)}.svg" alt="" onerror="this.style.visibility='hidden'">` : `<span class="gen">${icon('i-box')}</span>`;
    return `<tr><td class="nm"><button type="button" class="gname" data-guest="${g.type}|${g.vmid}" title="${esc(t('guest.history', { name: g.name }))}">${logo}${esc(g.name)}</button></td>
      <td>${g.vmid}</td><td><span class="type">${kindLabel(g.type)}</span></td>
      <td>${run ? `<span class="stp"><span class="dot ok"></span>${t('guest.running')}</span>` : `<span class="stp mute"><span class="dot off"></span>${t('guest.stopped')}</span>`}</td>
      <td>${run ? fmt.pct((g.cpu || 0) * 100) : '—'}</td><td>${run ? fmt.bytes(g.mem) : '—'}</td>
      <td>${svc ? `<button class="lnk" type="button" data-url="${esc(svc.url)}">${esc(svc.key)} ${icon('i-ext')}</button>` : ''}</td>
      <td><div class="acts"><button type="button" data-needs="guest_actions" data-act="${g.type}|${g.vmid}|${run ? 'shutdown' : 'start'}|${esc(g.name)}" title="${t(run ? 'guest.shutdown' : 'guest.start')}">${icon(run ? 'i-stop' : 'i-start')}</button>
        ${run ? `<button type="button" data-needs="guest_actions" data-act="${g.type}|${g.vmid}|reboot|${esc(g.name)}" title="${t('guest.reboot')}">${icon('i-restart')}</button>` : ''}
        <button type="button" data-needs="consoles" data-console="${g.type}|${g.vmid}|${esc(g.name)}" title="${t('guest.console')}">${icon('i-term')}</button></div></td></tr>`;
  }).join('');
  $$('#guestrows [data-url]').forEach((b) => (b.onclick = () => ctx.openUrl(b.dataset.url)));
  $$('#guestrows [data-guest]').forEach((b) => (b.onclick = () => {
    const [type, id] = b.dataset.guest.split('|');
    const g = st.guests.find((x) => x.type === type && String(x.vmid) === id);
    if (g) openHistory(g, b);
  }));
  $$('#guestrows [data-console]').forEach((b) => (b.onclick = () => {
    const [type, id, name] = b.dataset.console.split('|');
    // Inside the menu, signed in as this user; the Proxmox web console is the fallback.
    const web = () => ctx.openUrl(`${ctx.pveUrl()}/?console=${type === 'qemu' ? 'kvm' : 'lxc'}&novnc=1&vmid=${id}&vmname=${encodeURIComponent(name)}&node=${st.pub.node}`);
    ctx.openConsole({ vmid: +id, name, type }, web);
  }));
  $$('#guestrows [data-act]').forEach((b) => (b.onclick = async () => {
    const [type, id, act, name] = b.dataset.act.split('|');
    if (act !== 'start') {
      const r = act === 'reboot';
      const ok = await confirmBox(t(r ? 'guest.confirm_reboot' : 'guest.confirm_shutdown', { name }),
        t(r ? 'guest.confirm_reboot_text' : 'guest.confirm_shutdown_text'), t(r ? 'guest.reboot' : 'guest.shutdown'));
      if (!ok) return;
    }
    try { await api.post(`/api/guests/${type}/${id}/${act}`); toast(t('guest.sent', { name })); setTimeout(ctx.refreshDash, 1500); }
    catch (e) { toast(e.message, true); }
  }));
}

/* ---------------- a guest's history ---------------- */
let shown = null, back = null, range = 'hour', loading = 0;
const RANGES = ['hour', 'day', 'week'];

function openHistory(g, fromButton) {
  shown = g;
  back = fromButton;
  $('#gTitle').textContent = `${g.name} · ${kindLabel(g.type)} ${g.vmid}`;
  paintRange();
  $('#guestLayer').hidden = false;
  $(`#gRange [data-range="${range}"]`).focus();
  load();
  loadInfo();
}

// Latest backup and snapshots: they don't depend on the chart's period, so loaded once.
async function loadInfo() {
  const g = shown;
  $('#gExtra').innerHTML = '';
  let d;
  try { d = await api.get(`/api/guests/${g.type}/${g.vmid}/info`); } catch { return; }
  if (shown !== g) return;
  const when = (ts) => {
    const days = Math.floor((Date.now() / 1000 - ts) / 86400);
    return days < 1 ? t('guest.today') : t('guest.ago', { d: days });
  };
  const date = (ts) => new Date(ts * 1000).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' });
  const parts = [];
  if (d.backup) {
    parts.push(`<section><b>${esc(t('guest.backup'))}</b>${d.backup.last
      ? `<span>${esc(when(d.backup.last))} · ${esc(t('guest.backup_copies', { n: d.backup.count, size: fmt.bytes(d.backup.size) }))}</span>`
      : `<span class="bad">${esc(t('guest.backup_none'))}</span>`}</section>`);
  }
  if (d.snapshots) {
    parts.push(`<section><b>${esc(t('guest.snapshots'))}</b>${d.snapshots.length
      ? `<ul class="snaps">${d.snapshots.slice(0, 6).map((s) => `<li><span class="sn">${esc(s.name)}${s.ram ? ` <span class="pill dim">${esc(t('guest.snap_ram'))}</span>` : ''}</span>
          <small class="mute">${esc(date(s.time))}${s.desc ? ` · ${esc(s.desc)}` : ''}</small></li>`).join('')}</ul>`
      : `<span class="mute">${esc(t('guest.snap_none'))}</span>`}</section>`);
  }
  $('#gExtra').innerHTML = parts.join('');
}

function closeHistory() {
  $('#guestLayer').hidden = true;
  shown = null;
  if (back?.isConnected) back.focus();
  else $(`#guestrows [data-guest]`)?.focus();
}

function paintRange() {
  $('#gRange').innerHTML = RANGES.map((r) => `<button type="button" data-range="${r}" aria-pressed="${r === range}">${esc(t('guest.range_' + r))}</button>`).join('');
  $$('#gRange [data-range]').forEach((b) => (b.onclick = () => { range = b.dataset.range; paintRange(); $(`#gRange [data-range="${range}"]`).focus(); load(); }));
}

async function load() {
  const g = shown, my = ++loading;
  $('#gCharts').innerHTML = `<div class="wload" role="progressbar" aria-label="${esc(t('widget.loading'))}"></div>`;
  let d;
  try { d = await api.get(`/api/guests/${g.type}/${g.vmid}/rrd?timeframe=${range}`); }
  catch (e) { if (my === loading) $('#gCharts').innerHTML = `<div class="werr">${esc(e.message)}</div>`; return; }
  if (my !== loading || shown !== g) return; // a newer range or another guest was asked for meanwhile
  if (!d.cpu.some((v) => v != null)) { $('#gCharts').innerHTML = `<div class="mute">${esc(t('guest.no_history'))}</div>`; return; }
  // "Now" is the guest's state now: a stopped guest is off, whatever it did before.
  const now = (v, f) => (!running(g) || v == null ? t('guest.off_now') : f(v));
  const rate = (v) => `${fmt.bytes(v)}/${t('unit.s')}`;
  const block = (title, value, chart, foot = '') => `<section class="gchart"><div class="gch"><b>${esc(title)}</b><span>${value}</span></div>${chart}${foot}</section>`;
  $('#gCharts').innerHTML =
    block(t('guest.cpu'), esc(now(last(d.cpu), (v) => `${fmt.pct(v)} · ${t('guest.peak', { v: fmt.pct(peak(d.cpu)) })}`)),
      lines([{ values: d.cpu, color: 'var(--acc)', fill: true }], { max: 100, label: t('guest.cpu') }))
    + block(t('guest.mem'), esc(now(last(d.mem), (v) => `${fmt.bytes(v)} / ${fmt.bytes(d.maxmem)}`)),
      lines([{ values: d.mem, color: 'var(--acc2, #7fd1ff)', fill: true }], { max: d.maxmem, label: t('guest.mem') }))
    + block(t('guest.net'), esc(now(last(d.netin), (v) => `↓ ${rate(v)} · ↑ ${rate(last(d.netout) || 0)}`)),
      lines([{ values: d.netin, color: 'var(--ok, #5fd08a)', fill: true }, { values: d.netout, color: 'var(--acc)' }], { label: t('guest.net') }),
      `<div class="glegend"><span><i style="background:var(--ok, #5fd08a)"></i>${esc(t('guest.net_in'))}</span><span><i style="background:var(--acc)"></i>${esc(t('guest.net_out'))}</span></div>`);
}

/* ---------------- setup ---------------- */
export function init(c) {
  ctx = c;
  $$('[data-pane=guests] [data-sort]').forEach((b) => (b.onclick = () => {
    const by = b.dataset.sort;
    // a new column starts with what is most useful on top: busiest, running first, A→Z, lowest ID
    sort = sort.by === by ? { by, dir: -sort.dir } : { by, dir: ['cpu', 'mem'].includes(by) ? -1 : 1 };
    try { localStorage.setItem(SORT_KEY, JSON.stringify(sort)); } catch {}
    render();
  }));
  $('#guestFilter').addEventListener('input', (e) => { filter = e.target.value; render(); });
  $('#guestFilter').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && filter) { e.stopPropagation(); e.preventDefault(); filter = ''; e.target.value = ''; render(); }
  });
  $('#gClose').onclick = closeHistory;
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#guestLayer').hidden) { e.stopImmediatePropagation(); closeHistory(); }
  }, true);
}

// Signed out: no filter, no open history, for the next person.
export function reset() {
  filter = '';
  $('#guestFilter').value = '';
  if (!$('#guestLayer').hidden) $('#guestLayer').hidden = true;
  shown = null;
}
