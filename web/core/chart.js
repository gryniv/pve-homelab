// Small SVG line charts for history (a guest's CPU, memory, network). A null value is a gap:
// the guest was off, so the line breaks instead of dropping to zero.

const W = 300, H = 64, PAD = 3;

// series: [{ values: [n|null], color, fill? }]; max: the top of the scale (at least the data's peak).
export function lines(series, { max = 0, label = '' } = {}) {
  const peak = Math.max(max, ...series.flatMap((s) => s.values.filter((v) => v != null)), 0) || 1;
  const n = Math.max(...series.map((s) => s.values.length), 2);
  const x = (i) => (i * W) / (n - 1);
  const y = (v) => H - PAD - (v / peak) * (H - 2 * PAD);
  const paths = series.map((s) => {
    let d = '', area = '', run = [];
    const flush = () => {
      if (run.length > 1) {
        const line = run.map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
        d += line + ' ';
        area += `${line} L${x(run[run.length - 1][0]).toFixed(1)} ${H} L${x(run[0][0]).toFixed(1)} ${H} Z `;
      }
      run = [];
    };
    s.values.forEach((v, i) => (v == null ? flush() : run.push([i, v])));
    flush();
    return (s.fill && area ? `<path d="${area}" fill="${s.color}" opacity=".18"/>` : '')
      + (d ? `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>` : '');
  }).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${label}">${paths}</svg>`;
}

// The last value that is not a gap, and the largest one.
export const last = (values) => [...values].reverse().find((v) => v != null) ?? null;
export const peak = (values) => values.reduce((m, v) => (v != null && v > m ? v : m), 0);
