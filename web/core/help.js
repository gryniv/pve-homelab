// The keyboard help (?): every key the menu understands.
import { $, t, esc } from './ui.js';

const KEYS = [
  ['help.k_nav', '← → ↑ ↓'], ['help.k_tab', 'Tab · Shift+Tab'], ['help.k_open', 'Enter'], ['help.k_back', 'Esc'],
  ['help.k_search', 'a…z'], ['help.k_move', 'Alt + ← →'], ['help.k_dock', 'Alt+Q'], ['help.k_console', 'Ctrl+Alt+Q'],
  ['help.k_both_ctrl', 'Ctrl + Ctrl'], ['help.k_pad', 'A · B · Start · LB/RB · Guide'], ['help.k_help', '?'],
];

export function show() {
  $('#helpTable').innerHTML = KEYS.map(([k, keys]) => `<tr><td>${esc(t(k))}</td><td><span class="kbd">${esc(keys)}</span></td></tr>`).join('');
  $('#helpLayer').hidden = false;
  $('#helpClose').focus();
}

const hide = () => { $('#helpLayer').hidden = true; };

// `screen()` tells which screen is shown: on a VM's screen "?" belongs to the guest.
export function init(screen) {
  $('#helpClose').onclick = hide;
  addEventListener('keydown', (e) => {
    if (e.key === '?' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName) && screen() !== 'console') { e.preventDefault(); show(); }
    else if (e.key === 'Escape' && !$('#helpLayer').hidden) { e.stopImmediatePropagation(); hide(); }
  }, true);
}
