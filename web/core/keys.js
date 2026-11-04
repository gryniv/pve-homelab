// A key "pressed" by something that is not a keyboard (a gamepad, a phone remote): a synthetic
// keydown on the focused element, so every key handler of the menu reacts as to a real key. Enter
// and Space also do what a real key would do to a button or a link: click it.

const CODES = { Enter: 'Enter', Escape: 'Escape', ' ': 'Space', Tab: 'Tab', Backspace: 'Backspace',
  ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown' };

export function press(key, opts = {}) {
  const target = document.activeElement && document.activeElement !== document.body ? document.activeElement : document.body;
  const init = { key, code: CODES[key] || (key.length === 1 ? `Key${key.toUpperCase()}` : key), bubbles: true, cancelable: true, ...opts };
  const go = target.dispatchEvent(new KeyboardEvent('keydown', init));
  target.dispatchEvent(new KeyboardEvent('keyup', init));
  if (!go) return;   // a handler took it
  if (key === 'Enter' || key === ' ') {
    if (target.matches('button, a[href], summary, [role=button], [role=tab], label')) target.click();
    else if (target.matches('input[type=checkbox], input[type=radio]')) target.click();
    else if (target.form && target.matches('input, select')) target.form.requestSubmit();
  }
}
