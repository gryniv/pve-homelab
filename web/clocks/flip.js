/* @name.uk Перекидний
   @name.en Flip
   @desc.uk картки, що перегортаються
   @desc.en split-flap cards
   @order 40 */
// Split-flap cards; a digit flips when it changes.
export const css = `
.clock[data-clockk="flip"]{display:inline-flex;gap:.06em;align-items:center;font-weight:700;font-size:6.4em;letter-spacing:0}
.clock[data-clockk="flip"] .card{position:relative;display:inline-block;width:.72em;padding:.08em 0;text-align:center;border-radius:.1em;
  background:linear-gradient(180deg,rgba(28,32,42,.92) 50%,rgba(20,23,31,.92) 50%);box-shadow:0 .06em .2em rgba(0,0,0,.45);overflow:hidden}
.clock[data-clockk="flip"] .card::after{content:"";position:absolute;left:0;right:0;top:50%;height:.012em;background:rgba(0,0,0,.6)}
.clock[data-clockk="flip"] .card.go{animation:flipC .5s ease}
@keyframes flipC{0%{transform:rotateX(0)}45%{transform:rotateX(80deg);filter:brightness(.6)}100%{transform:rotateX(0)}}
.clock[data-clockk="flip"] .sep{opacity:.6;margin:0 .02em;font-size:.8em}
.sv .clock[data-clockk="flip"]{font-size:8.5em}
`;

export function render(el, t) {
  const digits = (t.h + t.m).split('');
  if (!el.firstChild) {
    el.innerHTML = '<span class="card"></span><span class="card"></span><span class="sep">:</span><span class="card"></span><span class="card"></span>';
  }
  el.querySelectorAll('.card').forEach((c, i) => {
    if (c.textContent === digits[i]) return;
    const first = c.textContent === '';
    c.textContent = digits[i];
    if (!first) { c.classList.remove('go'); void c.offsetWidth; c.classList.add('go'); }
  });
}
