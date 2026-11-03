// Full-screen view of a guest inside the menu: a VM's display or a container's terminal
// (noVNC over the backend's websocket relay, with the user's own Proxmox ticket).
import RFB from '/vendor/novnc/core/rfb.js';
import { $, t } from './ui.js';

let rfb = null;

export async function open(api, vm, onClosed) {
  close();
  $('#consoleName').textContent = vm.name;
  $('#consoleState').textContent = t('console.connecting');
  const type = vm.type === 'lxc' ? 'lxc' : 'qemu';
  const { token, password } = await api.post(`/api/console/${vm.vmid}?type=${type}`);
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
