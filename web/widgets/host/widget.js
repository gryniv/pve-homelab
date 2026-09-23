// Стан хоста: кільця CPU / RAM / температура, графік CPU за 30 хв у колонці.
const C = 2 * Math.PI * 20;

function ring(color, pct, label) {
  const v = Math.max(0, Math.min(100, pct));
  return `<div class="ring"><svg viewBox="0 0 48 48"><circle class="bg" cx="24" cy="24" r="20"/>
    <circle class="fg" cx="24" cy="24" r="20" stroke="${color}" stroke-dasharray="${(C * v / 100).toFixed(1)} ${C.toFixed(1)}"/></svg>
    <span><div>${label}</div></span></div>`;
}

function spark(hist) {
  if (hist.length < 3) return '<div class="spark-wait">графік CPU з\'явиться за хвилину</div>';
  const pts = hist;
  const max = Math.max(20, ...pts);
  const step = 200 / (pts.length - 1);
  const line = pts.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)} ${(38 - (v / max) * 34).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 200 40" preserveAspectRatio="none" aria-label="CPU за 30 хвилин">
    <path d="${line} L200 40 L0 40 Z" fill="var(--acc-soft)"/><path d="${line}" fill="none" stroke="var(--acc)" stroke-width="1.6"/></svg>`;
}

export default {
  title: 'Стан хоста',
  zones: ['login', 'side'],
  public: true,
  source: '/api/host',
  every: 5,
  css: true,
  render(h, { zone, ui, app }) {
    const memGb = ui.fmt.gb(h.mem_used), totGb = ui.fmt.gb(h.mem_total);
    const rings = ring('#ff8a3d', h.cpu, `<b>${Math.round(h.cpu)}%</b><small>CPU</small>`)
      + ring('#6fb4ff', (h.mem_used / h.mem_total) * 100, `${memGb}<small>з ${totGb} ГБ</small>`)
      + ring('#f5c451', h.temp ?? 0, `${h.temp ?? '—'}°<small>ТЕМП</small>`);
    const g = app.guestCounts();
    return `<h4>${zone === 'side' ? `Хост<span class="sp"></span><span style="text-transform:none;letter-spacing:0">${ui.fmt.uptime(h.uptime)}</span>` : 'Хост зараз'}</h4>
      <div class="rings">${rings}</div>
      ${zone === 'side' ? spark(h.cpu_hist) : `<div class="foot-line"><span class="mute">Гості</span><span><b class="ok">${g.running}</b> працюють · <b>${g.stopped}</b> стоп</span></div>`}`;
  },
};
