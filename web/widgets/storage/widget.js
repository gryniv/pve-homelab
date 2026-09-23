// Proxmox storages and how full they are.
export default {
  i18n: {
    uk: { title: 'Сховища', opt_only: 'Лише ці сховища', opt_only_hint: 'по одному в рядку; порожньо = усі', opt_free: 'Показувати вільне місце', free: 'вільно {v}' },
    en: { title: 'Storage', opt_only: 'Only these storages', opt_only_hint: 'one per line; empty = all', opt_free: 'Show free space', free: '{v} free' },
  },
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
