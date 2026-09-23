// Сховища Proxmox із заповненістю.
export default {
  title: 'Сховища',
  zones: ['side'],
  source: '/api/storage',
  every: 60,
  render(list, { ui }) {
    return `<h4>Сховища</h4>` + list.map((s) => `
      <div class="kv"><span class="mute">${ui.esc(s.id)}</span><b>${ui.fmt.bytes(s.used)} / ${ui.fmt.bytes(s.total)}</b></div>
      <div class="bar"><i style="width:${((s.used / s.total) * 100).toFixed(1)}%"></i></div>`).join('');
  },
};
