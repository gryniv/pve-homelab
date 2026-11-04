// Several time zones at a glance.
export default {
  zones: ['side', 'login'],
  public: true,
  every: 15,
  options: [
    { key: 'zones', type: 'list', label: 'opt_zones', hint: 'opt_zones_hint', default: 'Europe/London\nAmerica/New_York\nAsia/Tokyo', placeholder: 'Europe/Warsaw\nЛісабон=Europe/Lisbon' },
    { key: 'h12', type: 'toggle', label: 'opt_h12', default: false },
  ],
  i18n: {
    uk: { title: 'Світовий час', opt_zones: 'Часові пояси', opt_zones_hint: 'по одному в рядку: Europe/Warsaw або Назва=Europe/Warsaw', opt_h12: '12-годинний формат', bad: 'невідомий пояс', tomorrow: 'завтра', yesterday: 'вчора' },
    en: { title: 'World clock', opt_zones: 'Time zones', opt_zones_hint: 'one per line: Europe/Warsaw or Name=Europe/Warsaw', opt_h12: '12-hour format', bad: 'unknown zone', tomorrow: 'tomorrow', yesterday: 'yesterday' },
  },
  render(_d, { ui, t, opts }) {
    const now = new Date(), loc = ui.locale();
    const dayKey = (tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
    const here = dayKey(undefined);
    const rows = opts.zones.map((line) => {
      const [a, b] = line.includes('=') ? line.split('=') : [null, line];
      const tz = b.trim();
      const name = (a || tz.split('/').pop().replace(/_/g, ' ')).trim();
      try {
        const time = new Intl.DateTimeFormat(loc, { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: !!opts.h12 }).format(now);
        const d = dayKey(tz);
        const rel = d > here ? t('tomorrow') : d < here ? t('yesterday') : '';
        return `<div class="wc"><span>${ui.esc(name)}${rel ? `<small>${rel}</small>` : ''}</span><b>${ui.esc(time)}</b></div>`;
      } catch {
        return `<div class="wc"><span>${ui.esc(name)}<small>${t('bad')}</small></span><b>—</b></div>`;
      }
    }).join('');
    return `<h4>${t('title')}</h4>${rows}`;
  },
};
