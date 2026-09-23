// Keyboard-only navigation (the seat often has no mouse):
//  - arrow keys move focus to the nearest control in that direction, like a TV menu;
//  - Tab stays inside an open overlay (launch, settings, confirm);
//  - an overlay focuses its main control when it opens.

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const TEXT_INPUT = /^(INPUT|TEXTAREA|SELECT)$/;

function visible(el) {
  if (el.closest('[hidden]')) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

// The layer that currently owns the keyboard: topmost open overlay, else the visible screen.
export function activeLayer() {
  const layers = [...document.querySelectorAll('#confirmLayer, [data-layer]')].filter((l) => !l.hidden);
  if (layers.length) return layers[0].id === 'confirmLayer' ? layers[0] : layers[layers.length - 1];
  return [...document.querySelectorAll('body > .scr')].find((s) => !s.hidden) || document.body;
}

const candidates = (root) => [...root.querySelectorAll(FOCUSABLE)].filter(visible);

function move(dir) {
  const root = activeLayer();
  const list = candidates(root);
  const cur = document.activeElement;
  if (!list.length) return;
  if (!root.contains(cur) || cur === document.body) { list[0].focus(); return; }
  // Use the whole card as the reference box when focus is on a control inside it.
  const a = (cur.closest('.sys') || cur).getBoundingClientRect();
  const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  const horiz = dir === 'left' || dir === 'right';
  let best = null, bestScore = Infinity;
  for (const el of list) {
    if (el === cur || (cur.closest('.sys') && cur.closest('.sys').contains(el))) continue;
    const b = el.getBoundingClientRect();
    const bx = b.left + b.width / 2, by = b.top + b.height / 2;
    const dx = bx - ax, dy = by - ay;
    const main = dir === 'left' ? -dx : dir === 'right' ? dx : dir === 'up' ? -dy : dy;
    if (main <= 2) continue;
    // Same row/column ("in the beam") always wins over something diagonal, like a TV remote.
    const inBeam = horiz ? b.top < a.bottom && b.bottom > a.top : b.left < a.right && b.right > a.left;
    const cross = horiz ? Math.abs(dy) : Math.abs(dx);
    const score = (inBeam ? 0 : 1e6) + main + cross * 2.5;
    if (score < bestScore) { bestScore = score; best = el; }
  }
  if (best) { best.focus(); best.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
}

export function focusFirst(root = activeLayer(), prefer) {
  const el = (prefer && root.querySelector(prefer)) || candidates(root)[0];
  el?.focus();
}

export function init() {
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (document.body.classList.contains('console')) return; // keys belong to the VM
    const dirs = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
    if (dirs[e.key] && !e.altKey && !e.ctrlKey && !e.metaKey) {
      // Text fields keep their own arrows, except up/down leave a single-line input.
      if (TEXT_INPUT.test(t.tagName) && !(t.tagName === 'INPUT' && (e.key === 'ArrowUp' || e.key === 'ArrowDown'))) return;
      e.preventDefault();
      move(dirs[e.key]);
    }
    if (e.key === 'Tab') {
      const root = activeLayer();
      const list = candidates(root);
      if (!list.length) return;
      const i = list.indexOf(document.activeElement);
      e.preventDefault();
      const next = i < 0 ? 0 : (i + (e.shiftKey ? -1 : 1) + list.length) % list.length;
      list[next].focus();
    }
  });
  // First key press shows where focus is, even if nothing was focused yet.
  document.addEventListener('keydown', (e) => {
    if (document.body.classList.contains('console')) return;
    if (document.activeElement === document.body && /^(Arrow|Tab|Enter)/.test(e.key)) {
      e.preventDefault();
      e.stopPropagation();
      focusFirst();
    }
  }, true);
}
