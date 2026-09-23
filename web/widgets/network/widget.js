// Host network: traffic on the default-route interface and load.
export default {
  i18n: {
    uk: { title: 'Мережа', traffic: 'Трафік', mbit: 'Мбіт/с', address: 'Адреса', load: 'Навантаження' },
    en: { title: 'Network', traffic: 'Traffic', mbit: 'Mbit/s', address: 'Address', load: 'Load' },
  },
  zones: ['side', 'login'],
  public: true,
  source: '/api/host',
  every: 5,
  render(h, { app, t }) {
    return `<h4>${t('title')}</h4>
      <div class="kv"><span class="mute">${t('traffic')}</span><b>↓ ${h.net_rx_mbit} · ↑ ${h.net_tx_mbit} ${t('mbit')}</b></div>
      <div class="kv"><span class="mute">${t('address')}</span><b>${app.pub().ip}</b></div>
      <div class="kv"><span class="mute">${t('load')}</span><b>${h.load.toFixed(2)}</b></div>`;
  },
};
