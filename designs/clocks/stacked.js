/* @name.uk Стовпчик
   @name.en Stacked
   @desc.uk години над хвилинами
   @desc.en hours over minutes
   @order 30 */
// Hours above minutes, minutes in the accent colour.
export const css = `
.clock[data-clockk="stacked"]{display:inline-flex;flex-direction:column;line-height:.82;font-weight:800;font-size:5.4em}
.clock[data-clockk="stacked"] .mm{color:var(--acc)}
.sv .clock[data-clockk="stacked"]{font-size:7.5em}
`;

export function render(el, t) {
  if (!el.firstChild) el.innerHTML = '<span class="hh"></span><span class="mm"></span>';
  const [h, m] = [el.querySelector('.hh'), el.querySelector('.mm')];
  if (h.textContent !== t.h) h.textContent = t.h;
  if (m.textContent !== t.m) m.textContent = t.m;
}
