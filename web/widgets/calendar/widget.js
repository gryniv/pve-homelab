// Month calendar with today marked.
export default {
  zones: ['side', 'login'],
  public: true,
  every: 300,
  options: [
    { key: 'weekstart', type: 'select', label: 'opt_week', default: '1', choices: [['1', 'mon'], ['0', 'sun']] },
    { key: 'weeknum', type: 'toggle', label: 'opt_weeknum', default: false },
  ],
  render(_d, { ui, opts }) {
    const now = new Date(), y = now.getFullYear(), m = now.getMonth();
    const start = +opts.weekstart;
    const loc = ui.locale();
    const wd = Array.from({ length: 7 }, (_, i) => new Intl.DateTimeFormat(loc, { weekday: 'narrow' }).format(new Date(2024, 0, 7 + start + i)));
    const first = new Date(y, m, 1), days = new Date(y, m + 1, 0).getDate();
    const lead = (first.getDay() - start + 7) % 7;
    const cells = [...Array(lead).fill(''), ...Array.from({ length: days }, (_, i) => i + 1)];
    while (cells.length % 7) cells.push('');
    const weekNo = (d) => { const t = new Date(Date.UTC(y, m, d)); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); return Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / 864e5 + 1) / 7); };
    let rows = '';
    for (let r = 0; r < cells.length; r += 7) {
      const wk = cells.slice(r, r + 7);
      const firstDay = wk.find((x) => x) || 1;
      rows += `<tr>${opts.weeknum ? `<td class="wn">${weekNo(firstDay)}</td>` : ''}${wk.map((d, i) =>
        `<td class="${d === now.getDate() ? 'today' : ''}${(start + i) % 7 === 0 || (start + i) % 7 === 6 ? ' we' : ''}">${d}</td>`).join('')}</tr>`;
    }
    const title = new Intl.DateTimeFormat(loc, { month: 'long', year: 'numeric' }).format(now);
    return `<h4>${ui.esc(title)}</h4><table class="cal"><thead><tr>${opts.weeknum ? '<th></th>' : ''}${wd.map((x) => `<th>${ui.esc(x)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
  },
};
