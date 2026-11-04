// When each guest was last backed up (local dumps and Proxmox Backup Server).
export default {
  zones: ['side'],
  source: (ctx) => ctx.app.api.get(`/api/backups?days=${encodeURIComponent(ctx.opts.days)}`),
  every: 900,
  options: [
    { key: 'days', type: 'number', label: 'opt_days', hint: 'opt_days_hint', default: 7, min: 1, max: 365 },
    { key: 'list', type: 'number', label: 'opt_list', default: 5, min: 0, max: 30 },
  ],
  render(b, { ui, t, opts }) {
    if (!b.guests.length) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('empty')}</div>`;
    const when = (x) => {
      if (!x.last) return t('never');
      const d = Math.floor((Date.now() / 1000 - x.last) / 86400);
      return d < 1 ? t('today') : t('ago', { d });
    };
    const head = b.stale
      ? `<div class="sum"><b class="bad">${b.stale}</b><span class="mute">${t('of', { n: b.guests.length })}<br>${t('stale', { d: b.days })}</span></div>`
      : `<div class="allok"><span class="dot ok"></span>${t('all_ok')}</div>`;
    const n = Math.max(0, Number(opts.list) || 0);
    const rows = b.guests.filter((x) => x.stale).slice(0, n);
    const rest = b.stale - rows.length;
    return `<h4>${t('title')}</h4>${head}
      ${rows.map((x) => `<div class="row"><span class="dot ${x.last ? 'off' : 'bad'}"></span>
        <span class="nm">${ui.esc(x.name || String(x.vmid))}<small class="mute">${x.type === 'lxc' ? 'CT' : 'VM'} ${x.vmid}</small></span>
        <small class="${x.last ? 'mute' : 'bad'}">${when(x)}</small></div>`).join('')}
      ${rows.length && rest > 0 ? `<div class="mute more">${t('more', { n: rest })}</div>` : ''}`;
  },
};
