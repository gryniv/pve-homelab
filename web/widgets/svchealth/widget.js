// Are the web services up? A summary, and which ones are down.
export default {
  zones: ['side'],
  source: (ctx) => Promise.resolve(ctx.app.services()),
  every: 10,
  options: [
    { key: 'list', type: 'select', label: 'opt_list', default: 'down', choices: [['down', 'l_down'], ['all', 'l_all'], ['none', 'l_none']] },
  ],
  i18n: {
    uk: { title: 'Сервіси', opt_list: 'Список під підсумком', l_down: 'лише ті, що впали', l_all: 'усі сервіси', l_none: 'не показувати', up: 'працюють', ok: 'Усе працює', down: 'не відповідає' },
    en: { title: 'Services', opt_list: 'List under the summary', l_down: 'only the ones down', l_all: 'all services', l_none: "don't show", up: 'up', ok: 'All up', down: 'not responding' },
  },
  render(list, { ui, t, opts }) {
    const known = list.filter((s) => s.status);
    const up = known.filter((s) => s.status === 'running');
    const down = known.filter((s) => s.status !== 'running');
    const rows = opts.list === 'all' ? known : opts.list === 'down' ? down : [];
    return `<h4>${t('title')}</h4>
      <div class="sh"><b class="${down.length ? 'bad' : 'ok'}">${up.length}/${known.length}</b><span class="mute">${down.length ? t('up') : t('ok')}</span></div>
      <div class="bar"><i style="width:${known.length ? (up.length / known.length) * 100 : 0}%;${down.length ? '' : 'background:var(--ok)'}"></i></div>
      ${rows.map((s) => `<div class="sr"><span class="dot ${s.status === 'running' ? 'ok' : 'bad'}"></span><span>${ui.esc(s.name)}</span>
        ${s.status !== 'running' ? `<small class="bad">${t('down')}</small>` : ''}</div>`).join('')}`;
  },
};
