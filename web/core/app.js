// PVE Seat front end: screens, login, dashboard, launching systems.

import { api, SEAT } from './api.js';
import * as scene from './scene.js';
import * as W from './widgets.js';
import * as S from './settings.js';
import * as nav from './nav.js';
import * as vnc from './console.js';
import * as tabs from './tabs.js';
import { $, $$, icon, esc, avatar, fmt, toast, confirmBox, keepFocus } from './ui.js';

const st = {
  pub: null, me: null, prefs: null, screen: null,
  selUser: null, services: [], guests: [], systems: [],
  wx: null, wxKey: '', wxAt: 0, lastInput: Date.now(), timers: [],
};

/* ---------------- app facade given to widgets & settings ---------------- */
const app = {
  api, go,
  pub: () => st.pub,
  seat: () => st.pub.seat,
  prefs: () => st.prefs || {},
  me: () => st.me,
  loggedIn: () => !!st.me,
  services: () => st.services,
  isNight: scene.isNight,
  avatarOf: (u) => avatar(u, u.avatar ?? st.prefs?.avatar),
  guestCounts: () => st.pub.guests,
  openSettings: (s) => { S.open(s); go('settings'); },
  openUrl: (url) => tabs.open(url),
  pveUrl: () => (st.services.find((s) => s.key === 'pve')?.url) || `https://${st.pub.ip}:8006`,
  applyPrefs, weather,
};

/* ---------------- weather ---------------- */
async function weather(force = false) {
  const p = st.prefs?.weather || {};
  const city = p.city || st.pub.weather.city, units = p.units || st.pub.weather.units;
  const key = city + '|' + units;
  if (!force && st.wx && st.wxKey === key && Date.now() - st.wxAt < 600000) return st.wx;
  st.wx = await api.get(`/api/weather?city=${encodeURIComponent(city)}&units=${units}`);
  st.wxKey = key; st.wxAt = Date.now();
  paintWeather();
  return st.wx;
}

function paintWeather() {
  const w = st.wx;
  if (!w) return;
  scene.configure({ kind: w.kind });
  const night = scene.isNight();
  const src = `/assets/wx/${{ clear: night ? 'clear-night' : 'clear-day', partly: night ? 'partly-cloudy-night' : 'partly-cloudy-day', overcast: night ? 'overcast-night' : 'overcast-day', rain: 'rain', thunder: 'thunderstorms', snow: 'snow', fog: 'fog' }[w.kind]}.svg`;
  $$('[data-wx-icon]').forEach((i) => (i.src = src));
  $$('[data-temp]').forEach((x) => (x.textContent = w.temp + (w.units === 'f' ? '°F' : '°')));
  $$('[data-wx-text]').forEach((x) => (x.textContent = w.text));
  $$('[data-city]').forEach((x) => (x.textContent = w.city));
}

/* ---------------- look ---------------- */
function applyLook(skin, background) {
  document.body.dataset.skin = skin || 'dusk';
  document.body.dataset.bg = background || 'scene';
}

function applyPrefs({ relayout = false } = {}) {
  const p = st.prefs;
  applyLook(p.skin, p.background);
  scene.configure({ react: p.weather_react, byTime: p.sky_by_time, fx: p.saver.fx });
  $('.scr-saver').classList.toggle('sv-clockless', !p.saver.clock);
  paintMe();
  if (relayout) W.renderZone('side', p.layout.side || [], { app });
  renderServices();
}

function paintMe() {
  if (!st.me) return;
  const av = avatar(st.me, st.prefs.avatar);
  $$('[data-me-av]').forEach((a) => { a.style.background = av.bg; a.innerHTML = av.inner; });
  $$('[data-whoami]').forEach((x) => (x.textContent = st.me.id));
}

/* ---------------- screens ---------------- */
function go(screen) {
  if (['dash', 'settings', 'launch', 'console'].includes(screen) && !st.me) screen = 'login';
  if (screen !== 'console' && vnc.isOpen()) vnc.close();
  const base = ['settings', 'launch'].includes(screen) ? 'dash' : screen;
  const prevBase = ['settings', 'launch'].includes(st.screen) ? 'dash' : st.screen;
  if (base !== prevBase && (base === 'dash' || base === 'login')) {
    // One staggered entrance per screen change; periodic re-renders must not replay it.
    document.body.classList.add('entering');
    clearTimeout(go.t);
    go.t = setTimeout(() => document.body.classList.remove('entering'), 1400);
  }
  $$('body > .scr').forEach((el) => (el.hidden = el.dataset.scr !== base));
  $$('[data-layer]').forEach((l) => (l.hidden = l.dataset.layer !== screen));
  document.body.classList.toggle('in', base === 'dash');
  document.body.classList.toggle('saver', screen === 'saver');
  document.body.classList.toggle('console', screen === 'console');
  if (screen === 'settings') S.render();
  const prev = st.screen;
  st.screen = screen;
  scene.fxRun(screen !== 'console');
  if (screen === 'console') return;
  // Keyboard-only seat: always put focus somewhere sensible on the new screen.
  setTimeout(() => {
    if (screen === 'login') $('#pw').focus();
    else if (screen === 'launch') nav.focusFirst(undefined, '#mOpts .opt.sel:not([disabled])') ;
    else if (screen === 'settings') nav.focusFirst(undefined, '[data-sp][aria-selected="true"]');
    else if (screen === 'dash' && prev === 'launch' && lastSysBtn?.isConnected) lastSysBtn.focus();
    else if (screen === 'dash') nav.focusFirst(undefined, '.sys .play');
  }, 60);
}

/* ---------------- login ---------------- */
function renderUsers() {
  const users = st.pub.users;
  if (!st.selUser && users.length) st.selUser = users[0].id;
  $('#users').innerHTML = users.map((u, i) => {
    const av = avatar(u, u.avatar);
    return `<button class="user${u.id === st.selUser ? ' sel' : ''}" style="--i:${i + 4}" type="button" data-user="${esc(u.id)}">
      <span class="avw"><span class="av" style="background:${av.bg}">${av.inner}</span></span>
      <span class="nm">${esc(u.name)}</span><small>${esc(u.id)}</small></button>`;
  }).join('') + `<button class="user${st.selUser === '' ? ' sel' : ''}" type="button" data-user="">
      <span class="avw"><span class="av" style="background:rgba(255,255,255,.08)"><svg viewBox="0 0 24 24"><use href="#i-user"/></svg></span></span>
      <span class="nm">Інший</span><small>будь-який користувач</small></button>`;
  $$('[data-user]').forEach((b) => (b.onclick = () => selectUser(b.dataset.user)));
  selectUser(st.selUser ?? '', true);
}

function selectUser(id, initial = false) {
  st.selUser = id;
  $$('[data-user]').forEach((b) => b.classList.toggle('sel', b.dataset.user === id));
  const u = st.pub.users.find((x) => x.id === id);
  $('#otherRow').hidden = !!u;
  $('#pwLabel').textContent = u ? `Пароль для ${u.id}` : 'Пароль';
  $('#loginErr').hidden = true;
  applyLook(u?.skin, u?.background);
  W.renderZone('login', u?.login?.length ? u.login : ['weather', 'host'], { app });
  if (!initial) { $('#pw').value = ''; (u ? $('#pw') : $('#otherUser')).focus(); }
}

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const user = st.selUser || $('#otherUser').value.trim();
  if (!user) { $('#otherUser').focus(); return; }
  const btn = $('#loginBtn');
  btn.disabled = true;
  try {
    const r = await api.post('/api/login', { user, password: $('#pw').value });
    $('#pw').value = '';
    await enter(r.user, r.prefs);
  } catch (err) {
    $('#loginErr').textContent = err.message;
    $('#loginErr').hidden = false;
    $('#pw').select();
  } finally { btn.disabled = false; }
});

async function enter(userid, prefs) {
  const u = st.pub.users.find((x) => x.id === userid) || { id: userid, name: userid.split('@')[0] };
  st.me = { ...u };
  st.prefs = prefs;
  applyPrefs();
  W.stopZone('login');
  W.renderZone('side', prefs.layout.side || [], { app });
  go('dash');
  weather(true).catch(() => {});
  await refreshDash();
  // Systems arrive after the screen is shown; land keyboard focus on the first one.
  const a = document.activeElement;
  if (st.screen === 'dash' && (!a || a === document.body || a.closest('.top'))) nav.focusFirst(undefined, '.sys .play');
  st.timers.push(setInterval(refreshDash, 10000));
}

async function logout() {
  st.timers.splice(0).forEach(clearInterval);
  W.stopZone('side');
  try { await api.post('/api/logout'); } catch {}
  st.me = null; st.prefs = null;
  try { st.pub = await api.get('/api/public'); } catch {}
  renderUsers();
  go('login');
}
$('#logoutBtn').onclick = logout;

/* ---------------- dashboard ---------------- */
async function refreshDash() {
  if (!st.me) return;
  const [sys, svc, gst] = await Promise.allSettled([api.get('/api/systems'), api.get('/api/services'), api.get('/api/guests')]);
  const body = $('.scr-dash .body');
  if (sys.status === 'fulfilled') { st.systems = sys.value; keepFocus(body, renderSystems); }
  if (svc.status === 'fulfilled') { st.services = svc.value; keepFocus(body, renderServices); }
  if (gst.status === 'fulfilled') { st.guests = gst.value; keepFocus(body, renderGuests); }
  const bad = [sys, svc, gst].find((r) => r.status === 'rejected');
  if (bad?.reason?.status === 401) { toast('Сесія завершилась, увійди ще раз', true); logout(); }
}

const OS = [
  [/win/i, 'windows-11', 'radial-gradient(22em 14em at 75% 125%,#49b3ff 0,transparent 60%),radial-gradient(16em 12em at 110% -10%,#8a6bff99,transparent 60%),linear-gradient(135deg,#0b2f75,#06163a)'],
  [/ubuntu/i, 'ubuntu-linux', 'radial-gradient(20em 14em at 85% 115%,#ff7b3d 0,transparent 60%),linear-gradient(135deg,#5e2750,#2c001e)'],
  [/fedora/i, 'fedora', 'radial-gradient(20em 14em at 90% 110%,#51a2da 0,transparent 60%),linear-gradient(135deg,#294172,#0e1d3a)'],
  [/mac|osx/i, 'apple', 'radial-gradient(18em 12em at 20% 120%,#ffb46b 0,transparent 60%),linear-gradient(135deg,#ff9a6b,#c0508f 45%,#3f2b86)'],
  [/debian/i, 'debian', 'radial-gradient(20em 14em at 85% 115%,#d70a53 0,transparent 60%),linear-gradient(135deg,#3a0d1d,#12060b)'],
  [/.*/, 'linux', 'radial-gradient(20em 14em at 85% 115%,#6fb4ff 0,transparent 60%),linear-gradient(135deg,#1c2a3f,#0b1220)'],
];
const osOf = (vm) => OS.find(([re]) => re.test(`${vm.ostype} ${vm.name}`.replace(/^l26 /, '')) ) || OS[OS.length - 1];

function renderSystems() {
  const el = $('#systems');
  if (!st.systems.length) {
    el.innerHTML = `<div class="glass empty">Систем для запуску немає. Додай VM тег <b>seat</b> у Proxmox, і вона з'явиться тут.</div>`;
    return;
  }
  el.innerHTML = st.systems.map((vm, i) => {
    const [, logo, art] = osOf(vm);
    const run = vm.status === 'running';
    return `<div class="sys" style="--i:${i}"><div class="art" style="background:${art}"></div>
      <img class="os" src="/icons/${logo}.svg" alt="" style="${logo === 'apple' ? 'filter:invert(1)' : ''}" onerror="this.style.visibility='hidden'">
      <span class="state"><span class="dot ${run ? 'ok' : 'off'}"></span>${run ? `працює · ${fmt.uptime(vm.uptime)}` : vm.suspended ? 'приспана' : 'вимкнена'}</span>
      <h5>${esc(vm.name)}</h5><div class="meta"><span>VM ${vm.vmid}</span><span>${vm.cores} ядер · ${Math.round(vm.memory / 1024)} ГБ</span></div>
      <button class="play${run ? ' go' : ''}" type="button" data-sys="${i}" title="${run ? 'Перейти до' : 'Запустити'} ${esc(vm.name)}">
        <svg><use href="#${run ? 'i-arrow' : 'i-play'}"/></svg></button></div>`;
  }).join('');
  $$('[data-sys]').forEach((b) => (b.onclick = () => { lastSysBtn = b; openLaunch(st.systems[+b.dataset.sys]); }));
}

function renderServices() {
  if (!st.prefs) return;
  const hidden = st.prefs.hidden_services || [];
  const list = st.services.filter((s) => !hidden.includes(s.key));
  $('#svcCount').textContent = list.length;
  const down = st.services.filter((s) => s.status && s.status !== 'running');
  $('#health').classList.toggle('warn', down.length > 0);
  $('#health').title = down.length ? `Не працює: ${down.map((s) => s.name).join(', ')}` : 'усе в нормі';
  $('#svcgrid').innerHTML = list.map((s, i) => {
    const cls = s.status === 'running' ? '' : s.status ? ' down' : ' unknown';
    return `<button type="button" class="svc${cls}" style="--i:${i + 3}" data-url="${esc(s.url)}" title="${esc(s.desc || s.name)}">
      <span class="st"></span><span class="lg"><img src="/icons/${esc(s.icon || s.key)}.svg" alt=""
        onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'letter',textContent:'${esc(s.name[0])}'}))"></span>
      <span class="n">${esc(s.name)}</span><small>${esc(s.host)}</small></button>`;
  }).join('');
  $$('#svcgrid [data-url]').forEach((b) => (b.onclick = () => app.openUrl(b.dataset.url)));
}

function renderGuests() {
  $('#guestCount').textContent = st.guests.length;
  const svcBy = {};
  st.services.forEach((s) => { if (s.guest) (svcBy[s.guest.vmid] ||= s); });
  $('#guestrows').innerHTML = st.guests.map((g) => {
    const run = g.status === 'running', svc = svcBy[g.vmid];
    const logo = svc ? `<img src="/icons/${esc(svc.icon)}.svg" alt="" onerror="this.style.visibility='hidden'">` : `<span class="gen">${icon('i-box')}</span>`;
    return `<tr><td class="nm"><span>${logo}${esc(g.name)}</span></td><td>${g.vmid}</td><td><span class="type">${g.type === 'qemu' ? 'VM' : 'CT'}</span></td>
      <td>${run ? '<span class="stp"><span class="dot ok"></span>працює</span>' : '<span class="stp mute"><span class="dot off"></span>зупинено</span>'}</td>
      <td>${run ? fmt.pct((g.cpu || 0) * 100) : '—'}</td><td>${run ? fmt.bytes(g.mem) : '—'}</td>
      <td>${svc ? `<button class="lnk" type="button" data-url="${esc(svc.url)}">${esc(svc.key)} ${icon('i-ext')}</button>` : ''}</td>
      <td><div class="acts"><button type="button" data-act="${g.type}|${g.vmid}|${run ? 'shutdown' : 'start'}|${esc(g.name)}" title="${run ? 'Вимкнути' : 'Запустити'}">${icon(run ? 'i-stop' : 'i-start')}</button>
        ${run ? `<button type="button" data-act="${g.type}|${g.vmid}|reboot|${esc(g.name)}" title="Перезапустити">${icon('i-restart')}</button>` : ''}
        <button type="button" data-console="${g.type}|${g.vmid}|${esc(g.name)}" title="Консоль">${icon('i-term')}</button></div></td></tr>`;
  }).join('');
  $$('#guestrows [data-url]').forEach((b) => (b.onclick = () => app.openUrl(b.dataset.url)));
  $$('#guestrows [data-console]').forEach((b) => (b.onclick = () => {
    const [t, id, name] = b.dataset.console.split('|');
    app.openUrl(`${app.pveUrl()}/?console=${t === 'qemu' ? 'kvm' : 'lxc'}&novnc=1&vmid=${id}&vmname=${encodeURIComponent(name)}&node=${st.pub.node}`);
  }));
  $$('#guestrows [data-act]').forEach((b) => (b.onclick = async () => {
    const [t, id, act, name] = b.dataset.act.split('|');
    if (act !== 'start') {
      const ok = await confirmBox(act === 'reboot' ? `Перезапустити ${name}?` : `Вимкнути ${name}?`,
        act === 'reboot' ? 'Система коректно перезапуститься.' : 'Системі буде надіслано команду коректного вимкнення.',
        act === 'reboot' ? 'Перезапустити' : 'Вимкнути');
      if (!ok) return;
    }
    try { await api.post(`/api/guests/${t}/${id}/${act}`); toast(`${name}: команду надіслано`); setTimeout(refreshDash, 1500); }
    catch (e) { toast(e.message, true); }
  }));
}

$$('[data-ptab]').forEach((b) => (b.onclick = () => {
  $$('[data-ptab]').forEach((x) => x.setAttribute('aria-selected', x === b));
  $$('[data-pane]').forEach((p) => (p.hidden = p.dataset.pane !== b.dataset.ptab));
}));

/* ---------------- launch ---------------- */
let launchVm = null, launchGpu = null, polling = null, lastSysBtn = null;

function openLaunch(vm) {
  launchVm = vm;
  const [, logo, art] = osOf(vm);
  const run = vm.status === 'running';
  $('#mArt').style.background = art;
  $('#mLogo').src = `/icons/${logo}.svg`;
  $('#mLogo').style.filter = logo === 'apple' ? 'invert(1)' : '';
  $('#mTitle').textContent = vm.name;
  $('#mSub').textContent = `VM ${vm.vmid} · ${vm.cores} ядер · ${Math.round(vm.memory / 1024)} ГБ`;
  $('#mSteps').hidden = true; $('#mErr').hidden = true; $('#mOpts').hidden = false;
  $('#mStart').disabled = false; $('#mCancel').textContent = 'Скасувати';

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
    if (o.mode === 'virgl') return vm.suspended
      ? 'екран системи відкриється в цьому меню; 3D через VirGL запрацює після першого повного вимкнення'
      : 'ділиться з меню: 3D через VirGL, екран системи відкриється тут же, на весь екран';
    return o.is_seat_gpu ? 'вбудована, меню на цьому моніторі згасне' : 'віддається системі повністю, монітор перемкнеться на її вхід';
  };
  const info = run
    ? (vm.gpus.length ? 'Система вже працює. Монітор перемкнеться на неї, а меню лишиться працювати на своєму вході.' : 'Система вже працює. Її екран відкриється тут.')
    : 'Дискретна карта: монітор перемкнеться на неї і повернеться до меню, коли вимкнеш систему. Radeon (VirGL): система працює у вікні цього меню.';
  $('#mOpts').innerHTML = (opts.length ? opts.map((o) => {
    const color = o.vendor === 'nvidia' ? 'rgba(118,185,0,.16);color:#8fd400' : 'rgba(255,90,90,.14);color:#ff8f8f';
    const pill = o.mode === 'virgl' ? '<span class="pill dim">VirGL</span>' : o.is_seat_gpu ? '<span class="pill dim">iGPU</span>' : '<span class="pill here">цей монітор</span>';
    return `<button class="opt${o.pci === launchGpu ? ' sel' : ''}" type="button" data-gpu="${o.pci}" ${usable(o) ? '' : 'disabled'}>
      <span class="radio"></span><span class="chip" style="background:${color}">${icon(o.integrated ? 'i-chip' : 'i-gpu')}</span>
      <b>${esc(o.name)}</b>${pill}<small>${o.pci.slice(5)} · ${esc(noteOf(o))}</small></button>`;
  }).join('') : '<div class="errbox">До цього монітора не підключено жодної відеокарти, яку можна віддати системі.</div>')
    + `<div class="warnbox">${icon('i-info')}<span>${info}</span></div>`;
  $$('#mOpts [data-gpu]').forEach((b) => (b.onclick = () => {
    launchGpu = b.dataset.gpu;
    $$('#mOpts [data-gpu]').forEach((x) => x.classList.toggle('sel', x === b));
  }));
  $('#mStart').querySelector('span').textContent = run ? 'Перейти' : 'Запустити';
  $('#mStart').querySelector('use').setAttribute('href', run ? '#i-arrow' : '#i-play');
  $('#mStart').querySelector('svg').style.cssText = run ? '' : 'fill:currentColor;stroke:none';
  $('#mStart').disabled = !launchGpu;
  go('launch');
  if (!run && !st.prefs.launch.ask && launchGpu) startLaunch();
}

async function startLaunch() {
  if (!launchVm || !launchGpu) return;
  $('#mStart').disabled = true;
  $('#mErr').hidden = true;
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
          if (j.error) fail(j.error);
          else if (j.result?.console) openConsole(launchVm);
          else { $('#mCancel').textContent = 'Закрити'; setTimeout(() => { if (st.screen === 'launch') go('dash'); refreshDash(); }, 2500); }
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

$('#mStart').onclick = startLaunch;

/* ---------------- open service tabs ---------------- */
function renderOpenTabs(list) {
  const el = $('#openTabs');
  keepFocus(el, () => {
    el.innerHTML = list.map((t) => `
      <span class="otab"><button class="go" type="button" data-tab="${t.id}" title="${esc(t.url)}">
        ${t.icon ? `<img src="${esc(t.icon)}" alt="">` : icon('i-ext')}<span>${esc(t.title)}</span></button>
        <button class="x" type="button" data-tabx="${t.id}" title="Закрити ${esc(t.title)}">${icon('i-x')}</button></span>`).join('');
  });
  $$('[data-tab]', el).forEach((b) => (b.onclick = () => tabs.switchTo(+b.dataset.tab)));
  $$('[data-tabx]', el).forEach((b) => (b.onclick = () => tabs.close(+b.dataset.tabx)));
}

/* ---------------- console (VM screen inside the menu) ---------------- */
async function openConsole(vm) {
  go('console');
  try {
    await vnc.open(api, vm, (msg) => { if (st.screen === 'console') { toast(msg); go('dash'); refreshDash(); } });
  } catch (e) {
    toast(e.message, true);
    go('dash');
  }
}

function leaveConsole() {
  vnc.close();
  go('dash');
  refreshDash();
}
$('#consoleBack').onclick = leaveConsole;
// Ctrl+Alt+Q leaves the VM screen; caught before noVNC forwards keys to the guest.
addEventListener('keydown', (e) => {
  if (st.screen === 'console' && e.ctrlKey && e.altKey && (e.key === 'q' || e.key === 'Q' || e.code === 'KeyQ')) {
    e.preventDefault(); e.stopPropagation();
    leaveConsole();
  }
}, true);

/* ---------------- idle, clock, keys ---------------- */
['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'].forEach((ev) =>
  addEventListener(ev, () => { st.lastInput = Date.now(); if (st.screen === 'saver') go(st.me ? 'dash' : 'login'); }, { passive: true, capture: true }));

addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && ['settings', 'launch'].includes(st.screen)) go('dash');
});

$$('[data-go]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); go(b.dataset.go); }));

setInterval(() => {
  const idle = (Date.now() - st.lastInput) / 60000;
  if (st.screen === 'login' && idle >= st.pub.saver_after_min) go('saver');
  if (st.me && st.pub.lock_after_min && idle >= st.pub.lock_after_min && st.screen !== 'launch') logout();
}, 10000);

function tick() {
  const d = new Date();
  $$('[data-clock]').forEach((e) => (e.textContent = d.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' })));
  $$('[data-date]').forEach((e) => (e.textContent = d.toLocaleDateString('uk-UA', { weekday: 'long', day: 'numeric', month: 'long' })));
}

/* ---------------- boot ---------------- */
async function boot() {
  scene.init();
  nav.init();
  st.pub = await api.get('/api/public');
  for (const t of st.pub.themes) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = `/themes/${t.id}.css`;
    document.head.appendChild(l);
  }
  $$('[data-seat-name]').forEach((x) => (x.textContent = st.pub.seat.gpu_name));
  $$('[data-hostline]').forEach((x) => (x.textContent = `${st.pub.node} · Proxmox VE ${st.pub.version} · ${st.pub.ip}`));
  $$('[data-node]').forEach((x) => (x.textContent = st.pub.node));
  S.init(app);
  tabs.watch(renderOpenTabs);
  await W.load(st.pub.widgets);
  tick(); setInterval(tick, 10000);
  weather().catch(() => {});
  setInterval(() => weather(true).catch(() => {}), 900000);
  setInterval(async () => { try { const p = await api.get('/api/public'); st.pub.guests = p.guests; } catch {} }, 30000);
  try {
    const me = await api.get('/api/me');
    await enter(me.user, me.prefs);
  } catch {
    renderUsers();
    go('login');
  }
}

boot().catch((e) => {
  toast(`Не вдалося завантажити: ${e.message}`, true);
  setTimeout(() => location.reload(), 5000);
});
