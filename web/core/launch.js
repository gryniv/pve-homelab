// Launching a system: the dialog with the GPUs it can run on, the job's steps, and what follows
// (back to the dashboard, or the VM's screen inside the menu for VirGL).
import { api } from './api.js';
import { st } from './state.js';
import { $, $$, icon, esc, t } from './ui.js';

const OS = [
  [/win/i, 'windows-11', 'radial-gradient(22em 14em at 75% 125%,#49b3ff 0,transparent 60%),radial-gradient(16em 12em at 110% -10%,#8a6bff99,transparent 60%),linear-gradient(135deg,#0b2f75,#06163a)'],
  [/ubuntu/i, 'ubuntu-linux', 'radial-gradient(20em 14em at 85% 115%,#ff7b3d 0,transparent 60%),linear-gradient(135deg,#5e2750,#2c001e)'],
  [/fedora/i, 'fedora', 'radial-gradient(20em 14em at 90% 110%,#51a2da 0,transparent 60%),linear-gradient(135deg,#294172,#0e1d3a)'],
  [/mac|osx/i, 'apple', 'radial-gradient(18em 12em at 20% 120%,#ffb46b 0,transparent 60%),linear-gradient(135deg,#ff9a6b,#c0508f 45%,#3f2b86)'],
  [/debian/i, 'debian', 'radial-gradient(20em 14em at 85% 115%,#d70a53 0,transparent 60%),linear-gradient(135deg,#3a0d1d,#12060b)'],
  [/.*/, 'linux', 'radial-gradient(20em 14em at 85% 115%,#6fb4ff 0,transparent 60%),linear-gradient(135deg,#1c2a3f,#0b1220)'],
];
// [pattern, logo slug, card background] for a VM, from its OS type and name.
export const osOf = (vm) => OS.find(([re]) => re.test(`${vm.ostype} ${vm.name}`.replace(/^l26 /, ''))) || OS[OS.length - 1];

let launchVm = null, launchGpu = null, polling = null, lastBtn = null;
let ctx = null; // { go, refreshDash, openConsole } from app.js

// The card button the dialog was opened from: focus goes back to it afterwards.
export const lastButton = () => lastBtn;

// Signing out: a job still running must not touch the screen any more.
export function stop() { clearInterval(polling); }

export function open(vm, fromButton = null) {
  launchVm = vm;
  lastBtn = fromButton;
  const [, logo, art] = osOf(vm);
  const run = vm.status === 'running';
  $('#mArt').style.background = art;
  $('#mLogo').src = `/icons/${logo}.svg`;
  $('#mLogo').style.filter = logo === 'apple' ? 'invert(1)' : '';
  $('#mTitle').textContent = vm.name;
  $('#mSub').textContent = `VM ${vm.vmid} · ${t('cores', { n: vm.cores })} · ${t('gb', { n: Math.round(vm.memory / 1024) })}`;
  $('#mSteps').hidden = true; $('#mErr').hidden = true; $('#mOpts').hidden = false;
  $('#mStart').disabled = false; $('#mCancel').textContent = t('launch.cancel');

  // A running VM can only be joined where it already is: its passthrough GPU, or the menu (VirGL / no GPU).
  const opts = !run ? vm.options
    : vm.gpus.length ? vm.options.filter((o) => vm.gpus.includes(o.pci))
    : vm.options.filter((o) => o.mode === 'virgl');
  const usable = (o) => !o.disabled || (run && vm.gpus.includes(o.pci));
  const enabled = opts.filter(usable);
  const wantIgpu = st.prefs.launch.gpu === 'igpu';
  const pick = (wantIgpu && enabled.find((o) => o.is_seat_gpu)) || enabled.find((o) => !o.is_seat_gpu) || enabled[0];
  launchGpu = pick?.pci || null;

  const noteOf = (o) => {
    if (!usable(o)) return o.disabled;
    if (o.mode === 'virgl') return t(vm.suspended ? 'launch.note_virgl_suspended' : 'launch.note_virgl');
    return t(o.is_seat_gpu ? 'launch.note_seat' : 'launch.note_discrete');
  };
  const info = run
    ? t(vm.gpus.length ? 'launch.info_running_gpu' : 'launch.info_running_menu')
    : t('launch.info');
  $('#mOpts').innerHTML = (opts.length ? opts.map((o) => {
    const color = o.vendor === 'nvidia' ? 'rgba(118,185,0,.16);color:#8fd400' : 'rgba(255,90,90,.14);color:#ff8f8f';
    const pill = o.mode === 'virgl' ? '<span class="pill dim">VirGL</span>' : o.is_seat_gpu ? '<span class="pill dim">iGPU</span>' : `<span class="pill here">${t('launch.pill_monitor')}</span>`;
    return `<button class="opt${o.pci === launchGpu ? ' sel' : ''}" type="button" data-gpu="${o.pci}" ${usable(o) ? '' : 'disabled'}>
      <span class="radio"></span><span class="chip" style="background:${color}">${icon(o.integrated ? 'i-chip' : 'i-gpu')}</span>
      <b>${esc(o.name)}</b>${pill}<small>${o.pci.slice(5)} · ${esc(noteOf(o))}</small></button>`;
  }).join('') : `<div class="errbox">${esc(t('launch.no_gpus'))}</div>`)
    + `<div class="warnbox">${icon('i-info')}<span>${info}</span></div>`;
  $$('#mOpts [data-gpu]').forEach((b) => (b.onclick = () => {
    launchGpu = b.dataset.gpu;
    $$('#mOpts [data-gpu]').forEach((x) => x.classList.toggle('sel', x === b));
  }));
  $('#mStart').querySelector('span').textContent = t(run ? 'launch.go' : 'launch.start');
  $('#mStart').querySelector('use').setAttribute('href', run ? '#i-arrow' : '#i-play');
  $('#mStart').querySelector('svg').style.cssText = run ? '' : 'fill:currentColor;stroke:none';
  $('#mStart').disabled = !launchGpu;
  ctx.go('launch');
  if (!run && !st.prefs.launch.ask && launchGpu) start();
}

async function start() {
  if (!launchVm || !launchGpu) return;
  $('#mStart').disabled = true;
  $('#mErr').hidden = true;
  $('#mSteps').hidden = true; // a retry must not show the failed run's steps
  try {
    const job = await api.post('/api/launch', { vmid: launchVm.vmid, gpu: launchGpu });
    $('#mOpts').hidden = true;
    showJob(job);
    clearInterval(polling);
    polling = setInterval(async () => {
      try {
        const j = await api.get(`/api/jobs/${job.id}`);
        showJob(j);
        if (j.done) {
          clearInterval(polling);
          // Left the launch screen meanwhile: never pull the user into the VM, just refresh.
          if (st.screen !== 'launch') { ctx.refreshDash(); return; }
          if (j.error) fail(j.error);
          else if (j.result?.console) ctx.openConsole(launchVm);
          else { $('#mCancel').textContent = t('launch.close'); setTimeout(() => { if (st.screen === 'launch') ctx.go('dash'); ctx.refreshDash(); }, 2500); }
        }
      } catch (e) { clearInterval(polling); fail(e.message); }
    }, 500);
  } catch (e) { fail(e.message); }
}

function showJob(j) {
  const ol = $('#mSteps');
  ol.hidden = false;
  ol.innerHTML = j.steps.map((s) => `<li class="${s.state === 'todo' ? '' : s.state}">${esc(s.text)}</li>`).join('');
}

function fail(msg) {
  $('#mErr').textContent = msg;
  $('#mErr').hidden = false;
  $('#mOpts').hidden = false;
  $('#mStart').disabled = false;
}

export function init(c) {
  ctx = c;
  $('#mStart').onclick = start;
}
