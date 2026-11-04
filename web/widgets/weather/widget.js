// Weather: now + 3 days on the sign-in screen, compact in the side column.
export default {
  zones: ['login', 'side'],
  public: true,
  every: 900,
  options: [
    { key: 'days', type: 'select', label: 'opt_days', default: 'auto', choices: [['auto', 'd_auto'], ['0', 'd_0'], ['3', 'd_3'], ['4', 'd_4']] },
    { key: 'details', type: 'toggle', label: 'opt_details', default: true },
  ],
  source: (ctx) => ctx.app.weather(),
  render(w, { zone, ui, app, t, opts }) {
    const nDays = opts.days === 'auto' ? (zone === 'login' ? 3 : 0) : +opts.days;
    const details = opts.days === 'auto' ? zone === 'login' && opts.details : opts.details;
    const night = app.isNight();
    const unit = w.units === 'f' ? '°F' : '°';
    const fmtDay = new Intl.DateTimeFormat(ui.locale(), { weekday: 'short' });
    const days = w.days.slice(0, nDays).map((d) => `
      <div><span class="mute">${ui.esc(fmtDay.format(new Date(d.date)))}</span>
      <img src="${ui.wxIcon(d.kind, false)}" alt=""><b>${d.max}° / ${d.min}°</b></div>`).join('');
    return `
      <h4>${ui.esc(w.city)}<span class="sp"></span>
        ${app.loggedIn() ? `<button class="chipbtn" type="button" data-open-settings="weather" style="padding:.25em .45em" title="${t('configure')}">${ui.icon('i-gear')}</button>` : ''}</h4>
      <div class="wx-now"><img src="${ui.wxIcon(w.kind, night)}" alt="">
        <div><div class="wx-t">${w.temp}${unit}</div><div class="wx-d mute">${t('wx.' + w.kind)}</div></div></div>
      ${details ? `<div class="wx-d mute" style="margin-top:.4em">${t('wind', { v: w.wind, u: t(w.units === 'f' ? 'mph' : 'ms'), h: w.humidity })}</div>` : ''}
      ${nDays ? `<div class="wx-days" style="grid-template-columns:repeat(${nDays},1fr)">${days}</div>` : ''}`;
  },
  after(el, _w, { app }) {
    el.querySelector('[data-open-settings]')?.addEventListener('click', () => app.openSettings('weather'));
  },
};
