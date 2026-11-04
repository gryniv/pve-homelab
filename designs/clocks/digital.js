/* @name.uk Цифровий
   @name.en Digital
   @desc.uk великі цифри
   @desc.en big numbers
   @order 10 */
// The classic: HH:MM in the display font.
export const css = ``;

export function render(el, t) {
  if (el.textContent !== t.text) el.textContent = t.text;
}
