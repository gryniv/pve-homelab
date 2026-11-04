// The "Containers & VMs" table: every guest the user may see, with load, start/stop/reboot
// and a console inside the menu.
import { api } from './api.js';
import { st } from './state.js';
import { $, $$, icon, esc, fmt, toast, confirmBox, t, kindLabel } from './ui.js';

let ctx = null; // { openUrl, pveUrl, openConsole, refreshDash } from app.js

export function render() {
  $('#guestCount').textContent = st.guests.length;
  const svcBy = {};
  st.services.forEach((s) => { if (s.guest) (svcBy[s.guest.vmid] ||= s); });
  $('#guestrows').innerHTML = st.guests.map((g) => {
    const run = g.status === 'running', svc = svcBy[g.vmid];
    const logo = svc ? `<img src="/icons/${esc(svc.icon)}.svg" alt="" onerror="this.style.visibility='hidden'">` : `<span class="gen">${icon('i-box')}</span>`;
    return `<tr><td class="nm"><span>${logo}${esc(g.name)}</span></td><td>${g.vmid}</td><td><span class="type">${kindLabel(g.type)}</span></td>
      <td>${run ? `<span class="stp"><span class="dot ok"></span>${t('guest.running')}</span>` : `<span class="stp mute"><span class="dot off"></span>${t('guest.stopped')}</span>`}</td>
      <td>${run ? fmt.pct((g.cpu || 0) * 100) : '—'}</td><td>${run ? fmt.bytes(g.mem) : '—'}</td>
      <td>${svc ? `<button class="lnk" type="button" data-url="${esc(svc.url)}">${esc(svc.key)} ${icon('i-ext')}</button>` : ''}</td>
      <td><div class="acts"><button type="button" data-act="${g.type}|${g.vmid}|${run ? 'shutdown' : 'start'}|${esc(g.name)}" title="${t(run ? 'guest.shutdown' : 'guest.start')}">${icon(run ? 'i-stop' : 'i-start')}</button>
        ${run ? `<button type="button" data-act="${g.type}|${g.vmid}|reboot|${esc(g.name)}" title="${t('guest.reboot')}">${icon('i-restart')}</button>` : ''}
        <button type="button" data-console="${g.type}|${g.vmid}|${esc(g.name)}" title="${t('guest.console')}">${icon('i-term')}</button></div></td></tr>`;
  }).join('');
  $$('#guestrows [data-url]').forEach((b) => (b.onclick = () => ctx.openUrl(b.dataset.url)));
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

export function init(c) { ctx = c; }
