// Disk health (SMART) and ZFS pools of the node.
export default {
  zones: ['side'],
  source: '/api/disks',
  every: 600,
  options: [
    { key: 'only_bad', type: 'toggle', label: 'opt_only_bad', default: false },
  ],
  render(d, { ui, t, opts }) {
    if (!d.allowed) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('no_rights')}</div>`;
    const cls = (x) => (x.ok ? 'ok' : x.health === 'UNKNOWN' ? 'off' : 'bad');
    const pools = d.pools.filter((p) => !opts.only_bad || !p.ok);
    const disks = d.disks.filter((x) => !opts.only_bad || (!x.ok && x.health !== 'UNKNOWN'));
    const head = d.problems
      ? `<div class="sum"><b class="bad">${d.problems}</b><span class="mute">${t('problems')}</span></div>`
      : `<div class="allok"><span class="dot ok"></span>${t('all_ok')}</div>`;
    const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
    return `<h4>${t('title')}</h4>${head}
      ${pools.map((p) => `<div class="row"><span class="dot ${cls(p)}"></span><span class="nm">${ui.esc(p.name)} <small class="mute">${t('pool')}</small></span>
        <small class="${cls(p)}">${ui.esc(p.health)}</small></div>
        <div class="bar"><i style="width:${pct(p.alloc, p.size)}%"></i></div>`).join('')}
      ${disks.map((x) => `<div class="row"><span class="dot ${cls(x)}"></span>
        <span class="nm">${ui.esc(x.model || x.dev)}<small class="mute">${ui.esc(x.dev.replace('/dev/', ''))} · ${ui.fmt.bytes(x.size)}${x.wearout != null ? ` · ${t('life', { n: x.wearout })}` : ''}</small></span>
        <small class="${cls(x)}">${x.health === 'UNKNOWN' ? t('unknown') : ui.esc(x.health)}</small></div>`).join('')}`;
  },
};
