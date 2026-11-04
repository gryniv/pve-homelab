// Proxmox storages and how full they are.
export default {
  options: [
    { key: 'only', type: 'list', label: 'opt_only', hint: 'opt_only_hint', default: '', placeholder: 'local\nlocal-zfs' },
    { key: 'free', type: 'toggle', label: 'opt_free', default: false },
  ],
  zones: ['side'],
  source: '/api/storage',
  every: 60,
  render(list, { ui, t, opts }) {
    const rows = opts.only.length ? list.filter((s) => opts.only.includes(s.id)) : list;
    return `<h4>${t('title')}</h4>` + rows.map((s) => `
      <div class="kv"><span class="mute">${ui.esc(s.id)}</span><b>${opts.free ? t('free', { v: ui.fmt.bytes(s.total - s.used) }) : `${ui.fmt.bytes(s.used)} / ${ui.fmt.bytes(s.total)}`}</b></div>
      <div class="bar"><i style="width:${((s.used / s.total) * 100).toFixed(1)}%"></i></div>`).join('');
  },
};
