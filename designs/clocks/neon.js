/* @name.uk Неон
   @name.en Neon
   @desc.uk світний контур у кольорі теми
   @desc.en a glowing outline in the theme colour
   @order 60 */
// Outlined digits glowing in the accent colour; the colon blinks.
export const css = `
.clock[data-clockk="neon"]{color:transparent;-webkit-text-stroke:.02em var(--acc2);font-weight:800;
  text-shadow:0 0 .08em var(--acc),0 0 .25em color-mix(in srgb,var(--acc) 60%,transparent)}
.clock[data-clockk="neon"] .c{animation:neonC 1s steps(1) infinite}
@keyframes neonC{50%{opacity:.25}}
`;

export function render(el, t) {
  if (!el.firstChild) el.innerHTML = '<span class="h"></span><span class="c">:</span><span class="m"></span>';
  const [h, m] = [el.querySelector('.h'), el.querySelector('.m')];
  if (h.textContent !== t.h) h.textContent = t.h;
  if (m.textContent !== t.m) m.textContent = t.m;
}
