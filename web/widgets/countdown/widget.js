// Days left until a date you pick (a trip, a birthday, a release).
export default {
  zones: ['side', 'login'],
  public: true,
  every: 600,
  options: [
    { key: 'title', type: 'text', label: 'opt_title', default: '', placeholder: 'ph_title' },
    { key: 'date', type: 'date', label: 'opt_date', default: '' },
  ],
  i18n: {
    uk: { title: 'Зворотний відлік', opt_title: 'Подія', ph_title: 'напр. Відпустка', opt_date: 'Дата', days: '{n} дн.', today: 'Сьогодні!', passed: 'минуло {n} дн.', left: 'залишилось', none: 'Вибери подію й дату: ⚙ у налаштуваннях віджета.' },
    en: { title: 'Countdown', opt_title: 'Event', ph_title: 'e.g. Holiday', opt_date: 'Date', days: '{n} d', today: 'Today!', passed: '{n} d ago', left: 'to go', none: 'Pick an event and a date: ⚙ in the widget settings.' },
  },
  render(_d, { ui, t, opts }) {
    if (!opts.date) return `<h4>${t('title')}</h4><div class="mute" style="font-size:.85em">${t('none')}</div>`;
    const [y, m, d] = opts.date.split('-').map(Number);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const n = Math.round((new Date(y, m - 1, d) - today) / 864e5);
    const when = new Intl.DateTimeFormat(ui.locale(), { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(y, m - 1, d));
    const big = n === 0 ? t('today') : n > 0 ? t('days', { n }) : t('passed', { n: -n });
    return `<h4>${ui.esc(opts.title || t('title'))}</h4>
      <div class="cd"><b>${ui.esc(big)}</b>${n > 0 ? `<span class="mute">${t('left')}</span>` : ''}</div>
      <div class="mute" style="font-size:.8em">${ui.esc(when)}</div>`;
  },
};
