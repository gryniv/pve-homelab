// Full-screen view of a VM's display inside the menu (noVNC over the backend's websocket relay).
import RFB from '/vendor/novnc/core/rfb.js';
import { $, t } from './ui.js';

let rfb = null;

export async function open(api, vm, onClosed) {
  close();
  $('#consoleName').textContent = vm.name;
  $('#consoleState').textContent = t('console.connecting');
  const { token, password } = await api.post(`/api/console/${vm.vmid}`);
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/console/ws/${token}`;
  rfb = new RFB($('#vnc'), url, { credentials: { password }, wsProtocols: ['binary'] });
  rfb.scaleViewport = true;
  rfb.resizeSession = true;
  rfb.background = '#000';
  rfb.addEventListener('connect', () => { $('#consoleState').textContent = ''; rfb.focus(); });
  rfb.addEventListener('disconnect', (e) => {
    const was = rfb;
    rfb = null;
    if (was) onClosed(t(e.detail.clean ? 'console.closed' : 'console.lost'));
  });
}

export function close() {
  const r = rfb;
  rfb = null;
  if (r) r.disconnect();
  $('#vnc').innerHTML = '';
}

export const isOpen = () => !!rfb;
export const focus = () => rfb?.focus();
