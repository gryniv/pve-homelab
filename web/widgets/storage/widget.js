// Proxmox storages and how full they are.
export default {
  i18n: { uk: { title: 'Сховища' }, en: { title: 'Storage' } },
  zones: ['side'],
  source: '/api/storage',
  every: 60,
  render(list, { ui, t }) {
    return `<h4>${t('title')}</h4>` + list.map((s) => `
      <div class="kv"><span class="mute">${ui.esc(s.id)}</span><b>${ui.fmt.bytes(s.used)} / ${ui.fmt.bytes(s.total)}</b></div>
      <div class="bar"><i style="width:${((s.used / s.total) * 100).toFixed(1)}%"></i></div>`).join('');
  },
};
