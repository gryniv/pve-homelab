// Quick host actions. Proxmox itself checks the permission (Sys.PowerMgmt).
export default {
  zones: ['side'],
  options: [
    { key: 'buttons', type: 'checks', label: 'opt_buttons', default: ['pve', 'saver', 'reboot', 'shutdown'], choices: [['pve', 'pve'], ['saver', 'saver'], ['reboot', 'reboot'], ['shutdown', 'shutdown']] },
  ],
  render(_d, { ui, t, opts }) {
    const B = { pve: 'i-ext', saver: 'i-moon', reboot: 'i-restart', shutdown: 'i-power' };
    return `<h4>${t('title')}</h4><div class="qa">${Object.entries(B).filter(([k]) => opts.buttons.includes(k))
      .map(([k, ic]) => `<button type="button" data-q="${k}">${ui.icon(ic)}${t(k)}</button>`).join('')}</div>`;
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
