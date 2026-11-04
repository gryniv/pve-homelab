// Host network: traffic on the default-route interface and load.
export default {
  zones: ['side', 'login'],
  public: 'local',   // host figures: not on a browser elsewhere before sign-in
  options: [
    { key: 'show', type: 'checks', label: 'opt_show', default: ['traffic', 'address', 'load'], choices: [['traffic', 'traffic'], ['address', 'address'], ['load', 'load']] },
  ],
  source: '/api/host',
  every: 5,
  render(h, { app, t, opts }) {
    const on = (k) => opts.show.includes(k);
    return `<h4>${t('title')}</h4>
      ${on('traffic') ? `<div class="kv"><span class="mute">${t('traffic')}</span><b>↓ ${h.net_rx_mbit} · ↑ ${h.net_tx_mbit} ${t('mbit')}</b></div>` : ''}
      ${on('address') ? `<div class="kv"><span class="mute">${t('address')}</span><b>${app.pub().ip}</b></div>` : ''}
      ${on('load') ? `<div class="kv"><span class="mute">${t('load')}</span><b>${h.load.toFixed(2)}</b></div>` : ''}`;
  },
};
