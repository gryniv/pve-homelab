/* @name.uk Стрілковий
   @name.en Analog
   @desc.uk циферблат зі стрілками
   @desc.en a dial with hands
   @order 50 */
// A dial: white hour and minute hands, the second hand in the accent colour.
export const css = `
.clock[data-clockk="analog"]{display:inline-block;width:1.5em;height:1.5em;line-height:0}
.clock[data-clockk="analog"] svg{width:100%;height:100%;overflow:visible;filter:drop-shadow(0 .02em .06em rgba(0,0,0,.4))}
.clock[data-clockk="analog"] .face{fill:rgba(10,14,22,.35);stroke:rgba(255,255,255,.85);stroke-width:2}
.clock[data-clockk="analog"] .tk{stroke:rgba(255,255,255,.75);stroke-width:2;stroke-linecap:round}
.clock[data-clockk="analog"] .tk.b{stroke-width:4}
.clock[data-clockk="analog"] .hh,.clock[data-clockk="analog"] .mh{stroke:#fff;stroke-linecap:round}
.clock[data-clockk="analog"] .hh{stroke-width:6}.clock[data-clockk="analog"] .mh{stroke-width:4}
.clock[data-clockk="analog"] .sh{stroke:var(--acc);stroke-width:2;stroke-linecap:round}
.clock[data-clockk="analog"] .pin{fill:var(--acc)}
.clock[data-clockk="analog"] g{transform-origin:50px 50px;transition:transform .35s cubic-bezier(.4,2,.55,.44)}
.sv .clock[data-clockk="analog"]{width:1.2em;height:1.2em}
`;

const ticks = Array.from({ length: 12 }, (_, i) => {
  const a = (i * Math.PI) / 6, big = i % 3 === 0, r1 = big ? 38 : 41;
  return `<line class="tk${big ? ' b' : ''}" x1="${50 + r1 * Math.sin(a)}" y1="${50 - r1 * Math.cos(a)}" x2="${50 + 45 * Math.sin(a)}" y2="${50 - 45 * Math.cos(a)}"/>`;
}).join('');

export function render(el, t) {
  if (!el.firstChild) {
    el.innerHTML = `<svg viewBox="0 0 100 100"><circle class="face" cx="50" cy="50" r="48"/>${ticks}
      <g class="gh"><line class="hh" x1="50" y1="50" x2="50" y2="26"/></g>
      <g class="gm"><line class="mh" x1="50" y1="50" x2="50" y2="14"/></g>
      <g class="gs"><line class="sh" x1="50" y1="58" x2="50" y2="10"/></g><circle class="pin" cx="50" cy="50" r="3"/></svg>`;
  }
  const h = +t.h % 12, m = +t.m, s = +t.s;
  el.querySelector('.gh').style.transform = `rotate(${h * 30 + m / 2}deg)`;
  el.querySelector('.gm').style.transform = `rotate(${m * 6 + s / 10}deg)`;
  const gs = el.querySelector('.gs');
  // no backwards sweep from 59 to 0
  gs.style.transition = s === 0 ? 'none' : '';
  gs.style.transform = `rotate(${s * 6}deg)`;
}
