// Мережа хоста: швидкість на мосту vmbr0 та навантаження.
export default {
  title: 'Мережа',
  zones: ['side', 'login'],
  public: true,
  source: '/api/host',
  every: 5,
  render(h, { app }) {
    return `<h4>Мережа</h4>
      <div class="kv"><span class="mute">vmbr0</span><b>↓ ${h.net_rx_mbit} · ↑ ${h.net_tx_mbit} Мбіт/с</b></div>
      <div class="kv"><span class="mute">Адреса</span><b>${app.pub().ip}</b></div>
      <div class="kv"><span class="mute">Навантаження</span><b>${h.load.toFixed(2)}</b></div>`;
  },
};
