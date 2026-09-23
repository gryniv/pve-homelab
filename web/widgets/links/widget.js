// Your own bookmarks, opened as tabs next to the menu like the web services.
export default {
  zones: ['side'],
  css: true,
  options: [
    { key: 'links', type: 'list', label: 'opt_links', hint: 'opt_links_hint', default: 'Proxmox Docs | https://pve.proxmox.com/pve-docs/', placeholder: 'GitHub | https://github.com' },
  ],
  i18n: {
    uk: { title: 'Посилання', opt_links: 'Посилання', opt_links_hint: 'по одному в рядку: Назва | https://адреса', none: 'Додай свої посилання: ⚙ у налаштуваннях віджета.' },
    en: { title: 'Links', opt_links: 'Links', opt_links_hint: 'one per line: Name | https://address', none: 'Add your links: ⚙ in the widget settings.' },
  },
  render(_d, { ui, t, opts }) {
    const links = opts.links.map((l) => {
      const [a, b] = l.includes('|') ? l.split('|') : [l, l];
      const url = b.trim().match(/^https?:\/\//) ? b.trim() : 'https://' + b.trim();
      return { name: a.trim() || url, url, host: (() => { try { return new URL(url).host; } catch { return ''; } })() };
    });
    if (!links.length) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('none')}</div>`;
    return `<h4>${t('title')}</h4><div class="lk">${links.map((l) => `<button type="button" data-url="${ui.esc(l.url)}">
      <img src="https://www.google.com/s2/favicons?sz=64&domain=${encodeURIComponent(l.host)}" alt="" onerror="this.style.visibility='hidden'">
      <span>${ui.esc(l.name)}<small>${ui.esc(l.host)}</small></span></button>`).join('')}</div>`;
  },
  after(el, _d, { app }) {
    el.querySelectorAll('[data-url]').forEach((b) => b.addEventListener('click', () => app.openUrl(b.dataset.url)));
  },
};
