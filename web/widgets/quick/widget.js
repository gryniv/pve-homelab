// Quick host actions. Proxmox itself checks the permission (Sys.PowerMgmt).
export default {
  zones: ['side'],
  css: true,
  i18n: {
    uk: { title: 'Швидкі дії', pve: 'Вебінтерфейс PVE', saver: 'Заставка', reboot: 'Перезавантажити', shutdown: 'Вимкнути хост',
      reboot_q: 'Перезавантажити хост?', reboot_text: 'Усі VM і контейнери будуть перезапущені.',
      shutdown_q: 'Вимкнути хост?', shutdown_text: "Усі VM і контейнери зупиняться, комп'ютер вимкнеться.", shutdown_btn: 'Вимкнути',
      rebooting: 'Хост перезавантажується', stopping: 'Хост вимикається' },
    en: { title: 'Quick actions', pve: 'PVE web UI', saver: 'Screensaver', reboot: 'Reboot', shutdown: 'Shut down host',
      reboot_q: 'Reboot the host?', reboot_text: 'All VMs and containers will restart.',
      shutdown_q: 'Shut down the host?', shutdown_text: 'All VMs and containers stop and the computer powers off.', shutdown_btn: 'Shut down',
      rebooting: 'The host is rebooting', stopping: 'The host is shutting down' },
  },
  render(_d, { ui, t }) {
    return `<h4>${t('title')}</h4><div class="qa">
      <button type="button" data-q="pve">${ui.icon('i-ext')}${t('pve')}</button>
      <button type="button" data-q="saver">${ui.icon('i-moon')}${t('saver')}</button>
      <button type="button" data-q="reboot">${ui.icon('i-restart')}${t('reboot')}</button>
      <button type="button" data-q="shutdown">${ui.icon('i-power')}${t('shutdown')}</button></div>`;
  },
  after(el, _d, { app, ui, t }) {
    el.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', async () => {
      const q = b.dataset.q;
      if (q === 'pve') return app.openUrl(app.pveUrl());
      if (q === 'saver') return app.go('saver');
      const txt = q === 'reboot' ? [t('reboot_q'), t('reboot_text'), t('reboot')] : [t('shutdown_q'), t('shutdown_text'), t('shutdown_btn')];
      if (await ui.confirmBox(...txt)) {
        try { await app.api.post('/api/host/power', { cmd: q }); ui.toast(t(q === 'reboot' ? 'rebooting' : 'stopping')); }
        catch (e) { ui.toast(e.message, true); }
      }
    }));
  },
};
