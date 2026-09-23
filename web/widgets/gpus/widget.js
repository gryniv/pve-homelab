// Відеокарти: хто зараз тримає кожну карту і де ти сидиш.
export default {
  title: 'Відеокарти',
  zones: ['side'],
  source: '/api/gpus',
  every: 10,
  css: true,
  render(list, { ui, app }) {
    const seatGpu = app.seat().gpu;
    const rows = list.map((g) => {
      const mon = g.connectors.find((c) => c.connected);
      let where;
      if (g.running_vm) where = `у VM ${g.running_vm}`;
      else if (g.pci === seatGpu) where = mon ? `${mon.name} · меню` : 'меню';
      else where = g.driver === 'vfio-pci' ? 'вільна' : g.driver ? `вільна · ${g.driver}` : 'без драйвера';
      const color = g.vendor === 'nvidia' ? 'rgba(118,185,0,.16);color:#8fd400' : 'rgba(255,90,90,.14);color:#ff8f8f';
      const pill = g.pci === seatGpu ? '<span class="pill here">ти тут</span>'
        : g.integrated ? '<span class="pill dim">iGPU</span>' : '';
      return `<div class="gpu"><span class="chip" style="background:${color}">${ui.icon(g.integrated ? 'i-chip' : 'i-gpu')}</span>
        <div>${ui.esc(g.name)}${pill}</div><small>${g.pci.slice(5)} · ${ui.esc(where)}</small></div>`;
    }).join('');
    return `<h4>Відеокарти</h4>${rows}`;
  },
};
