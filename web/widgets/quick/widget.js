// Швидкі дії з хостом. Proxmox сам перевіряє права (Sys.PowerMgmt).
export default {
  title: 'Швидкі дії',
  zones: ['side'],
  css: true,
  render(_d, { ui }) {
    return `<h4>Швидкі дії</h4><div class="qa">
      <button type="button" data-q="pve">${ui.icon('i-ext')}Вебінтерфейс PVE</button>
      <button type="button" data-q="saver">${ui.icon('i-moon')}Заставка</button>
      <button type="button" data-q="reboot">${ui.icon('i-restart')}Перезавантажити</button>
      <button type="button" data-q="shutdown">${ui.icon('i-power')}Вимкнути хост</button></div>`;
  },
  after(el, _d, { app, ui }) {
    el.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', async () => {
      const q = b.dataset.q;
      if (q === 'pve') return app.openUrl(app.pveUrl());
      if (q === 'saver') return app.go('saver');
      const txt = q === 'reboot' ? ['Перезавантажити хост?', 'Усі VM і контейнери будуть перезапущені.', 'Перезавантажити']
        : ['Вимкнути хост?', 'Усі VM і контейнери зупиняться, комп\'ютер вимкнеться.', 'Вимкнути'];
      if (await ui.confirmBox(...txt)) {
        try { await app.api.post('/api/host/power', { cmd: q }); ui.toast(q === 'reboot' ? 'Хост перезавантажується' : 'Хост вимикається'); }
        catch (e) { ui.toast(e.message, true); }
      }
    }));
  },
};
