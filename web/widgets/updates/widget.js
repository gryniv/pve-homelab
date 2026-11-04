// Package updates waiting on the Proxmox node (the list Proxmox refreshes daily).
// "and N more" / "Details" opens the top bar's dialog: every package, and "Check now".
export default {
  zones: ['side'],
  source: '/api/node-updates',
  every: 1800,
  options: [
    { key: 'list', type: 'number', label: 'opt_list', hint: 'opt_list_hint', default: 4, min: 0, max: 20 },
  ],
  render(u, { ui, t, opts }) {
    if (!u.allowed) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('no_rights')}</div>`;
    const ago = u.checked ? t('checked', { ago: ui.fmt.ago(Math.max(60, Date.now() / 1000 - u.checked)) }) : '';
    if (!u.count) return `<h4>${t('title')}</h4><div class="up"><span class="dot ok"></span>${t('none')}</div>${ago ? `<div class="mute when">${ago}</div>` : ''}`;
    const n = Math.max(0, Number(opts.list) || 0);
    const shown = u.packages.slice(0, n);
    const rest = u.count - shown.length;
    return `<h4>${t('title')}</h4>
      <div class="sum"><b>${u.count}</b><span class="mute">${t('waiting')}${u.proxmox ? `<br>${t('from_pve', { n: u.proxmox })}` : ''}${ago ? `<br>${ago}` : ''}</span></div>
      ${u.kernel ? `<div class="kern">${ui.icon('i-restart')}<span>${t('kernel')}</span></div>` : ''}
      ${shown.map((p) => `<div class="pk"><span class="nm${p.origin === 'Proxmox' ? ' pve' : ''}">${ui.esc(p.name)}</span>
        <small class="mute">${p.old ? `${ui.esc(p.old)} → ` : `${t('new_pkg')} `}${ui.esc(p.new)}</small></div>`).join('')}
      <button type="button" class="lnk more" data-nu>${shown.length && rest > 0 ? t('more', { n: rest }) : t('details')}</button>`;
  },
  after(box, _u, { app }) {
    const b = box.querySelector('[data-nu]');
    if (b) b.onclick = () => app?.showNodeUpdates?.(b);
  },
};
