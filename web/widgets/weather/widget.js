// Weather: now + 3 days on the sign-in screen, compact in the side column.
export default {
  zones: ['login', 'side'],
  public: true,
  every: 900,
  css: true,
  i18n: {
    uk: { title: 'Погода', wind: 'вітер {v} {u} · вологість {h}%', ms: 'м/с', mph: 'mph', configure: 'Налаштувати погоду' },
    en: { title: 'Weather', wind: 'wind {v} {u} · humidity {h}%', ms: 'm/s', mph: 'mph', configure: 'Weather settings' },
  },
  source: (ctx) => ctx.app.weather(),
  render(w, { zone, ui, app, t }) {
    const night = app.isNight();
    const unit = w.units === 'f' ? '°F' : '°';
    const fmtDay = new Intl.DateTimeFormat(ui.locale(), { weekday: 'short' });
    const days = w.days.slice(0, 3).map((d) => `
      <div><span class="mute">${ui.esc(fmtDay.format(new Date(d.date)))}</span>
      <img src="${ui.wxIcon(d.kind, false)}" alt=""><b>${d.max}° / ${d.min}°</b></div>`).join('');
    return `
      <h4>${ui.esc(w.city)}<span class="sp"></span>
        ${app.loggedIn() ? `<button class="chipbtn" type="button" data-open-settings="weather" style="padding:.25em .45em" title="${t('configure')}">${ui.icon('i-gear')}</button>` : ''}</h4>
      <div class="wx-now"><img src="${ui.wxIcon(w.kind, night)}" alt="">
        <div><div class="wx-t">${w.temp}${unit}</div><div class="wx-d mute">${t('wx.' + w.kind)}</div></div></div>
      ${zone === 'login' ? `<div class="wx-d mute" style="margin-top:.4em">${t('wind', { v: w.wind, u: t(w.units === 'f' ? 'mph' : 'ms'), h: w.humidity })}</div><div class="wx-days">${days}</div>` : ''}`;
  },
  after(el, _w, { app }) {
    el.querySelector('[data-open-settings]')?.addEventListener('click', () => app.openSettings('weather'));
  },
};
