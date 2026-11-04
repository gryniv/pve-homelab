// VMs and containers with their state and load.
export default {
  zones: ['side'],
  source: '/api/guests',
  every: 10,
  options: [
    { key: 'show', type: 'select', label: 'opt_show', default: 'running', choices: [['running', 'running'], ['all', 'all']] },
    { key: 'types', type: 'checks', label: 'opt_types', default: ['qemu', 'lxc'], choices: [['qemu', 'vm'], ['lxc', 'ct']] },
    { key: 'limit', type: 'number', label: 'opt_limit', default: 6, min: 1, max: 30 },
  ],
  i18n: {
    uk: { title: 'Гості', opt_show: 'Показувати', running: 'лише працюючі', all: 'усі', opt_types: 'Типи', vm: 'віртуальні машини', ct: 'контейнери', opt_limit: 'Скільки рядків', none: 'Нічого не працює', more: 'і ще {n}' },
    en: { title: 'Guests', opt_show: 'Show', running: 'running only', all: 'all', opt_types: 'Types', vm: 'virtual machines', ct: 'containers', opt_limit: 'Rows', none: 'Nothing is running', more: 'and {n} more' },
  },
  render(list, { ui, t, opts }) {
    const rows = list.filter((g) => !g.template && opts.types.includes(g.type) && (opts.show === 'all' || g.status === 'running'))
      .sort((a, b) => (b.status === 'running') - (a.status === 'running') || b.cpu - a.cpu);
    const shown = rows.slice(0, opts.limit);
    return `<h4>${t('title')}<span class="sp"></span><span class="cnt">${rows.filter((g) => g.status === 'running').length}/${rows.length}</span></h4>
      ${shown.map((g) => `<div class="gr"><span class="dot ${g.status === 'running' ? 'ok' : 'off'}"></span>
        <span class="nm">${ui.esc(g.name)}<small>${g.type === 'lxc' ? 'CT' : 'VM'} ${g.vmid}</small></span>
        ${g.status === 'running' ? `<span class="ld"><i style="width:${Math.min(100, g.cpu * 100).toFixed(0)}%"></i></span><b>${(g.cpu * 100).toFixed(0)}%</b>` : ''}</div>`).join('')
      || `<div class="mute" style="font-size:.85em">${t('none')}</div>`}
      ${rows.length > shown.length ? `<div class="mute" style="font-size:.78em;margin-top:.3em">${t('more', { n: rows.length - shown.length })}</div>` : ''}`;
  },
};
