// A small clock for the dashboard, in any of the clock designs (designs/clocks).
import * as clocks from '/core/clocks.js';

export default {
  zones: ['side'],
  options: [
    { key: 'design', type: 'select', label: 'opt_design', default: '', choices: (app, lang) => [['', 'same'], ...app.pub().clocks.map((c) => [c.id, c.name[lang] || c.name.en])] },
    { key: 'date', type: 'toggle', label: 'opt_date', default: true },
  ],
  render(_d, { opts }) {
    return `<div class="clock wclk"></div>${opts.date ? '<div class="wdate mute"></div>' : ''}`;
  },
  after(el, _d, { app, ui, opts }) {
    const ck = el.querySelector('.wclk'), dt = el.querySelector('.wdate');
    const tick = () => {
      if (!el.isConnected) return clearInterval(timer);
      const d = new Date();
      clocks.paint(ck, opts.design || app.prefs()?.clock || 'digital', d, ui.locale());
      if (dt) dt.textContent = d.toLocaleDateString(ui.locale(), { weekday: 'long', day: 'numeric', month: 'long' });
    };
    const timer = setInterval(tick, 1000);
    tick();
  },
};
