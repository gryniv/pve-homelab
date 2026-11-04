// Host state: CPU / RAM / temperature rings; 30-minute CPU graph in the side column.
const C = 2 * Math.PI * 20;

function ring(color, pct, label) {
  const v = Math.max(0, Math.min(100, pct));
  return `<div class="ring"><svg viewBox="0 0 48 48"><circle class="bg" cx="24" cy="24" r="20"/>
    <circle class="fg" cx="24" cy="24" r="20" stroke="${color}" stroke-dasharray="${(C * v / 100).toFixed(1)} ${C.toFixed(1)}"/></svg>
    <span><div>${label}</div></span></div>`;
}

let waitText = '';
function spark(hist) {
  if (hist.length < 3) return `<div class="spark-wait">${waitText}</div>`;
  const pts = hist;
  const max = Math.max(20, ...pts);
  const step = 200 / (pts.length - 1);
  const line = pts.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)} ${(38 - (v / max) * 34).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 200 40" preserveAspectRatio="none" aria-label="CPU, 30 min">
    <path d="${line} L200 40 L0 40 Z" fill="var(--acc-soft)"/><path d="${line}" fill="none" stroke="var(--acc)" stroke-width="1.6"/></svg>`;
}

export default {
  zones: ['login', 'side'],
  public: true,
  source: '/api/host',
  every: 5,
  options: [
    { key: 'rings', type: 'checks', label: 'opt_rings', default: ['cpu', 'mem', 'temp'], choices: [['cpu', 'r_cpu'], ['mem', 'r_mem'], ['temp', 'r_temp']] },
    { key: 'graph', type: 'toggle', label: 'opt_graph', default: true },
  ],
  i18n: {
    uk: { title: 'Стан хоста', host: 'Хост', now: 'Хост зараз', of: 'з {n} ГБ', temp: 'ТЕМП', guests: 'Гості', running: '{n} працюють', stopped: '{n} стоп', wait: "графік CPU з'явиться за хвилину",
      opt_rings: 'Кільця', r_cpu: 'процесор', r_mem: "пам'ять", r_temp: 'температура', opt_graph: 'Графік CPU за 30 хв (на панелі)' },
    en: { title: 'Host', host: 'Host', now: 'Host now', of: 'of {n} GB', temp: 'TEMP', guests: 'Guests', running: '{n} running', stopped: '{n} stopped', wait: 'the CPU graph appears in a minute',
      opt_rings: 'Rings', r_cpu: 'CPU', r_mem: 'memory', r_temp: 'temperature', opt_graph: 'CPU graph, 30 min (dashboard)' },
  },
  render(h, { zone, ui, app, t, opts }) {
    waitText = t('wait');
    const memGb = ui.fmt.gb(h.mem_used), totGb = ui.fmt.gb(h.mem_total);
    const on = (k) => opts.rings.includes(k);
    const rings = (on('cpu') ? ring('#ff8a3d', h.cpu, `<b>${Math.round(h.cpu)}%</b><small>CPU</small>`) : '')
      + (on('mem') ? ring('#6fb4ff', (h.mem_used / h.mem_total) * 100, `${memGb}<small>${t('of', { n: totGb })}</small>`) : '')
      + (on('temp') ? ring('#f5c451', h.temp ?? 0, `${h.temp ?? '—'}°<small>${t('temp')}</small>`) : '');
    const g = app.guestCounts();
    return `<h4>${zone === 'side' ? `${t('host')}<span class="sp"></span><span style="text-transform:none;letter-spacing:0">${ui.fmt.uptime(h.uptime)}</span>` : t('now')}</h4>
      <div class="rings">${rings}</div>
      ${zone === 'side' ? (opts.graph ? spark(h.cpu_hist) : '') : `<div class="foot-line"><span class="mute">${t('guests')}</span><span><b class="ok">${t('running', { n: g.running })}</b> · ${t('stopped', { n: g.stopped })}</span></div>`}`;
  },
};
