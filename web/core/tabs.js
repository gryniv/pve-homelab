// Services open as tabs next to the menu (via the kiosk extension's bridge in content.js).
// Outside the kiosk (no extension) it falls back to window.open.

let bridge = false, seq = 0;
const pending = new Map();
let onTabs = () => {};

addEventListener('message', (e) => {
  if (e.source !== window || !e.data) return;
  if (e.data.pveseatBridge) bridge = true;
  if (e.data.pveseatReply && pending.has(e.data.pveseatReply)) {
    pending.get(e.data.pveseatReply)(e.data.res);
    pending.delete(e.data.pveseatReply);
  }
  if (e.data.pveseatTabs) onTabs(e.data.pveseatTabs);
});
postMessage({ pveseatPing: true }, location.origin);

function call(cmd) {
  if (!bridge) return Promise.resolve(null);
  const id = ++seq;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    postMessage({ pveseat: cmd, id }, location.origin);
    setTimeout(() => { if (pending.delete(id)) resolve(null); }, 3000);
  });
}

export const available = () => bridge;
export function open(url) { return bridge ? call({ cmd: 'open', url }) : Promise.resolve(window.open(url, '_blank')); }
export const list = () => call({ cmd: 'list' });
export const switchTo = (id) => call({ cmd: 'switch', id });
export const close = (id) => call({ cmd: 'close', id });
export function watch(fn) { onTabs = fn; list().then((l) => Array.isArray(l) && fn(l)); }
