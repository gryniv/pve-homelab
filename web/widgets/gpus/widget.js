// GPUs: who holds each card right now and which one you are sitting at.
export default {
  zones: ['side'],
  source: '/api/gpus',
  every: 10,
  css: true,
  i18n: {
    uk: { title: 'Відеокарти', in_vm: 'у VM {id}', menu: 'меню', free: 'вільна', no_driver: 'без драйвера', here: 'ти тут' },
    en: { title: 'GPUs', in_vm: 'in VM {id}', menu: 'menu', free: 'free', no_driver: 'no driver', here: 'you are here' },
  },
  render(list, { ui, app, t }) {
    const seatGpu = app.seat().gpu;
    const rows = list.map((g) => {
      const mon = g.connectors.find((c) => c.connected);
      let where;
      if (g.running_vm) where = t('in_vm', { id: g.running_vm });
      else if (g.pci === seatGpu) where = mon ? `${mon.name} · ${t('menu')}` : t('menu');
      else where = g.driver === 'vfio-pci' ? t('free') : g.driver ? `${t('free')} · ${g.driver}` : t('no_driver');
      const color = g.vendor === 'nvidia' ? 'rgba(118,185,0,.16);color:#8fd400' : 'rgba(255,90,90,.14);color:#ff8f8f';
      const pill = g.pci === seatGpu ? `<span class="pill here">${t('here')}</span>`
        : g.integrated ? '<span class="pill dim">iGPU</span>' : '';
      return `<div class="gpu"><span class="chip" style="background:${color}">${ui.icon(g.integrated ? 'i-chip' : 'i-gpu')}</span>
        <div>${ui.esc(g.name)}${pill}</div><small>${g.pci.slice(5)} · ${ui.esc(where)}</small></div>`;
    }).join('');
    return `<h4>${t('title')}</h4>${rows}`;
  },
};
