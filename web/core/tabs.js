// Services open as tabs next to the menu (via the kiosk extension's bridge in content.js).
// Outside the kiosk (no extension) it falls back to window.open.

let bridge = false, seq = 0;
const pending = new Map();
let onTabs = () => {};

addEventListener('message', (e) => {
  if (e.source !== window || !e.data) return;
  if (e.data.pvehomelabBridge) bridge = true;
  if (e.data.pvehomelabReply && pending.has(e.data.pvehomelabReply)) {
    pending.get(e.data.pvehomelabReply)(e.data.res);
    pending.delete(e.data.pvehomelabReply);
  }
  if (e.data.pvehomelabTabs) onTabs(e.data.pvehomelabTabs);
});
postMessage({ pvehomelabPing: true }, location.origin);

function call(cmd) {
  if (!bridge) return Promise.resolve(null);
  const id = ++seq;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    postMessage({ pvehomelab: cmd, id }, location.origin);
    setTimeout(() => { if (pending.delete(id)) resolve(null); }, 3000);
  });
}

export const available = () => bridge;
export function open(url) { return bridge ? call({ cmd: 'open', url }) : Promise.resolve(window.open(url, '_blank')); }
export const list = () => call({ cmd: 'list' });
export const switchTo = (id) => call({ cmd: 'switch', id });
export const close = (id) => call({ cmd: 'close', id });
// The dock on service pages is translated by the extension; tell it the current language.
export const setLang = (lang) => call({ cmd: 'lang', lang });
export function watch(fn) { onTabs = fn; list().then((l) => Array.isArray(l) && fn(l)); }
