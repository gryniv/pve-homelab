// Wake-on-LAN: switch on the machines listed under `wol:` in config.yaml.
export default {
  zones: ['side'],
  css: true,
  source: '/api/wol',
  every: 300,
  i18n: {
    uk: { title: 'Увімкнути', none: 'Машин для пробудження немає: додай їх у config.yaml (розділ wol).', no_rights: 'Будити машини можуть ті, хто має Sys.PowerMgmt на вузлі', sent: '{name}: сигнал надіслано', wake: 'Увімкнути {name}' },
    en: { title: 'Wake up', none: 'No machines to wake: add them to config.yaml (the wol section).', no_rights: 'Waking machines is for those with Sys.PowerMgmt on the node', sent: '{name}: wake-up sent', wake: 'Wake up {name}' },
  },
  render(d, { ui, t }) {
    if (!d.allowed) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('no_rights')}</div>`;
    if (!d.targets.length) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('none')}</div>`;
    return `<h4>${t('title')}</h4><div class="wk">${d.targets.map((x) => `<button type="button" data-wake="${x.id}" title="${ui.esc(t('wake', { name: x.name }))}">
      ${ui.icon('i-power')}<span>${ui.esc(x.name)}</span></button>`).join('')}</div>`;
  },
  after(box, _d, { app, ui, t }) {
    box.querySelectorAll('[data-wake]').forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      try { const r = await app.api.post(`/api/wol/${b.dataset.wake}`); ui.toast(t('sent', { name: r.name })); }
      catch (e) { ui.toast(e.message, true); }
      finally { setTimeout(() => (b.disabled = false), 3000); }
    }));
  },
};
