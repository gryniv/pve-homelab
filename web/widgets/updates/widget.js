// Package updates waiting on the Proxmox node (the list Proxmox refreshes daily).
export default {
  zones: ['side'],
  css: true,
  source: '/api/node-updates',
  every: 1800,
  options: [
    { key: 'list', type: 'number', label: 'opt_list', hint: 'opt_list_hint', default: 4, min: 0, max: 20 },
  ],
  i18n: {
    uk: {
      title: 'Оновлення Proxmox', opt_list: 'Скільки пакетів показувати', opt_list_hint: '0 = лише підсумок',
      none: 'Усе оновлено', waiting: 'чекають оновлення', from_pve: 'з них {n} від Proxmox',
      kernel: 'нове ядро: після оновлення знадобиться перезавантаження', more: 'і ще {n}',
      no_rights: 'Список оновлень бачать ті, хто може змінювати вузол (Sys.Modify)', new_pkg: 'новий',
    },
    en: {
      title: 'Proxmox updates', opt_list: 'Packages to list', opt_list_hint: '0 = summary only',
      none: 'Up to date', waiting: 'waiting to be installed', from_pve: '{n} of them from Proxmox',
      kernel: 'new kernel: a reboot will be needed after updating', more: 'and {n} more',
      no_rights: 'The update list is for those who may change the node (Sys.Modify)', new_pkg: 'new',
    },
  },
  render(u, { ui, t, opts }) {
    if (!u.allowed) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('no_rights')}</div>`;
    if (!u.count) return `<h4>${t('title')}</h4><div class="up"><span class="dot ok"></span>${t('none')}</div>`;
    const n = Math.max(0, Number(opts.list) || 0);
    const shown = u.packages.slice(0, n);
    const rest = u.count - shown.length;
    return `<h4>${t('title')}</h4>
      <div class="sum"><b>${u.count}</b><span class="mute">${t('waiting')}${u.proxmox ? `<br>${t('from_pve', { n: u.proxmox })}` : ''}</span></div>
      ${u.kernel ? `<div class="kern">${ui.icon('i-restart')}<span>${t('kernel')}</span></div>` : ''}
      ${shown.map((p) => `<div class="pk"><span class="nm${p.origin === 'Proxmox' ? ' pve' : ''}">${ui.esc(p.name)}</span>
        <small class="mute">${p.old ? `${ui.esc(p.old)} → ` : `${t('new_pkg')} `}${ui.esc(p.new)}</small></div>`).join('')}
      ${shown.length && rest > 0 ? `<div class="mute more">${t('more', { n: rest })}</div>` : ''}`;
  },
};
