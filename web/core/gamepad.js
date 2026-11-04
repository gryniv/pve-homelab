// A gamepad drives the menu like a TV remote (the browser's Gamepad API, standard mapping):
//   D-pad / left stick  arrows (held: repeats)      A  Enter     B  Esc
//   Start               settings                    View  keyboard help
//   LB / RB             previous / next tab          Guide  menu ↔ the system on this monitor
// It is read only while one is connected, and not while a VM's screen is in the menu.

import { press } from './keys.js';

const BUTTON = { 0: 'Enter', 1: 'Escape', 12: 'ArrowUp', 13: 'ArrowDown', 14: 'ArrowLeft', 15: 'ArrowRight' };
const REPEAT_FIRST = 400, REPEAT_NEXT = 120, DEAD = 0.55;
let ctx = null, running = false;
const held = {};   // button -> {since, last}

function stickKeys(pad) {
  const [x = 0, y = 0] = pad.axes || [];
  const out = [];
  if (x < -DEAD) out.push('ArrowLeft');
  if (x > DEAD) out.push('ArrowRight');
  if (y < -DEAD) out.push('ArrowUp');
  if (y > DEAD) out.push('ArrowDown');
  return out;
}

function act(name) {
  const screen = ctx.screen();
  if (name === 'guide') return ctx.seatSwitch();
  if (screen === 'away' || screen === 'console') return;          // the VM has the screen
  if (name === 'start') return ctx.openSettings();
  if (name === 'view') return press('?');
  if (name === 'lb' || name === 'rb') return ctx.pane(name === 'lb' ? -1 : 1);
  press(name);
}

function poll() {
  const pads = [...(navigator.getGamepads?.() || [])].filter(Boolean);
  if (!pads.length) { running = false; return; }
  const now = performance.now();
  const down = new Set();
  for (const pad of pads) {
    pad.buttons.forEach((b, i) => {
      if (!b.pressed) return;
      const name = BUTTON[i] || { 4: 'lb', 5: 'rb', 8: 'view', 9: 'start', 16: 'guide' }[i];
      if (name) down.add(name);
    });
    stickKeys(pad).forEach((k) => down.add(k));
  }
  for (const name of down) {
    const h = held[name];
    const repeats = name.startsWith('Arrow');
    if (!h) { held[name] = { since: now, last: now }; act(name); }
    else if (repeats && now - h.since > REPEAT_FIRST && now - h.last > REPEAT_NEXT) { h.last = now; act(name); }
  }
  for (const name of Object.keys(held)) if (!down.has(name)) delete held[name];
  requestAnimationFrame(poll);
}

function start() {
  if (running) return;
  running = true;
  ctx.wake?.();
  requestAnimationFrame(poll);
}

export function init(c) {
  ctx = c;
  addEventListener('gamepadconnected', start);
  if ([...(navigator.getGamepads?.() || [])].some(Boolean)) start();
}
