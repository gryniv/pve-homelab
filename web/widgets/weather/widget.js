// Погода: зараз + 3 дні (на екрані входу), компактно в лівій колонці.
const DAYS = ['Нд', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

export default {
  title: 'Погода',
  zones: ['login', 'side'],
  public: true,
  every: 900,
  source: (ctx) => ctx.app.weather(),
  render(w, { zone, ui, app }) {
    const night = app.isNight();
    const unit = w.units === 'f' ? '°F' : '°';
    const wind = w.units === 'f' ? 'mph' : 'м/с';
    const days = w.days.slice(0, 3).map((d) => `
      <div><span class="mute">${DAYS[new Date(d.date).getDay()]}</span>
      <img src="${ui.wxIcon(d.kind, false)}" alt=""><b>${d.max}° / ${d.min}°</b></div>`).join('');
    return `
      <h4>${ui.esc(w.city)}<span class="sp"></span>
        ${app.loggedIn() ? `<button class="chipbtn" type="button" data-open-settings="weather" style="padding:.25em .45em" title="Налаштувати погоду">${ui.icon('i-gear')}</button>` : ''}</h4>
      <div class="wx-now"><img src="${ui.wxIcon(w.kind, night)}" alt="">
        <div><div class="wx-t">${w.temp}${unit}</div><div class="wx-d mute">${w.text}</div></div></div>
      ${zone === 'login' ? `<div class="wx-d mute" style="margin-top:.4em">вітер ${w.wind} ${wind} · вологість ${w.humidity}%</div><div class="wx-days">${days}</div>` : ''}`;
  },
  after(el, _w, { app }) {
    el.querySelector('[data-open-settings]')?.addEventListener('click', () => app.openSettings('weather'));
  },
  css: true,
};
