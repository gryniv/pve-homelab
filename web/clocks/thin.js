/* @name.uk Тонкий
   @name.en Thin
   @desc.uk легкий, з секундною лінією
   @desc.en light, with a seconds line
   @order 20 */
// Light weight digits over a hairline that fills up every minute.
export const css = `
.clock[data-clockk="thin"]{font-weight:200;letter-spacing:.02em}
.clock[data-clockk="thin"] .ln{display:block;height:.025em;margin-top:.06em;background:rgba(255,255,255,.18);border-radius:1em;overflow:hidden}
.clock[data-clockk="thin"] .ln i{display:block;height:100%;background:var(--acc);transform-origin:left;transition:transform 1s linear}
`;

export function render(el, t) {
  if (!el.firstChild) el.innerHTML = '<span class="tx"></span><span class="ln"><i></i></span>';
  const tx = el.querySelector('.tx');
  if (tx.textContent !== t.text) tx.textContent = t.text;
  el.querySelector('.ln i').style.transform = `scaleX(${(+t.s + 1) / 60})`;
}
