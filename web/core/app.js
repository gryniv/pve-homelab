// PVE Homelab front end: screens, login, dashboard, launching systems.

import { api, SEAT } from './api.js';
import * as scene from './scene.js';
import * as W from './widgets.js';
import * as S from './settings.js';
import * as nav from './nav.js';
import * as vnc from './console.js';
import * as tabs from './tabs.js';
import { arrange, moved } from './order.js';
import { rail } from './rail.js';
import * as bg from './backgrounds.js';
import * as clocks from './clocks.js';
import * as fonts from './fonts.js';
import * as errlog from './errlog.js';
import * as i18n from './i18n.js';
import { $, $$, icon, esc, avatar, fmt, toast, confirmBox, keepFocus, t } from './ui.js';

const st = {
  pub: null, me: null, prefs: null, screen: null,
  selUser: null, services: [], guests: [], systems: [],
  wx: null, wxKey: '', wxAt: 0, lastInput: Date.now(), timers: [], loginLang: null, filter: '', sysView: [],
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
  systems: () => st.systems,
  updateStatus: () => upd,
  showHelp: () => showHelp(),
  isNight: scene.isNight,
  avatarOf: (u) => avatar(u, u.avatar ?? st.prefs?.avatar),
  guestCounts: () => st.pub.guests,
  openSettings: (s) => { S.open(s); go('settings'); },
  openUrl: (url) => tabs.open(url),
  pveUrl: () => (st.services.find((s) => s.key === 'pve')?.url) || `https://${st.pub.ip}:8006`,
  applyPrefs, weather, useLang: (code) => useLang(code), t, locale: () => i18n.locale(),
  setLoginSettings: (L) => { st.pub.login = L; },
};

/* ---------------- language ---------------- */
// Signed in: the user's choice. Sign-in screen: the switcher, else the selected user's language. Else config default.
function wantedLang() {
  if (st.me) return st.prefs?.lang || st.loginLang || st.pub.language;
  const u = st.pub?.users.find((x) => x.id === st.selUser);
  return st.loginLang || u?.lang || st.pub?.language || 'en';
}

async function useLang(code = wantedLang()) {
  if (await i18n.setLang(code)) {
    rerender();
    // City names come back from the geocoder in the requested language.
    if (st.pub) weather(true).then(() => st.me ? W.renderZone('side', st.prefs.layout.side || [], { app, opts: st.prefs.widget_opts }) : keepFocus($('#loginForm'), renderUsers)).catch(() => {});
  }
  tabs.setLang(i18n.current());
}

// Everything that holds translated text is rebuilt from state.
function rerender() {
  tick(); paintWeather(); renderLoginLang(); paintAbout();
  if (upd?.available) $('#updPill span').textContent = t('upd.pill', { v: updLabel(upd) });
  if (st.me) {
    W.renderZone('side', st.prefs.layout.side || [], { app, opts: st.prefs.widget_opts });
    const body = $('.scr-dash .body');
    keepFocus(body, renderSystems); keepFocus(body, renderServices); keepFocus(body, renderGuests);
    if (st.screen === 'settings') S.render();
  } else if (st.pub) {
    keepFocus($('#loginForm'), renderUsers);
  }
}

function renderLoginLang() {
  const el = $('#loginLang');
  if (!el || !st.pub) return;
  el.hidden = st.pub.languages.length < 2;
  keepFocus(el, () => {
    el.innerHTML = st.pub.languages.map((l) =>
      `<button type="button" data-v="${l.code}" aria-pressed="${l.code === i18n.current()}" title="${esc(l.name)}">${l.code.toUpperCase()}</button>`).join('');
  });
  $$('button', el).forEach((b) => (b.onclick = () => { st.loginLang = b.dataset.v; useLang(); }));
}

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
  $$('[data-wx-text]').forEach((x) => (x.textContent = t('wx.' + w.kind)));
  $$('[data-city]').forEach((x) => (x.textContent = w.city));
}

/* ---------------- look ---------------- */
// A look = theme, background, clock design and fonts: the signed-in user's, or on the
// sign-in screen the selected user's.
let clockId = 'digital';
function applyLook(look = {}) {
  document.body.dataset.skin = look.skin || 'dusk';
  document.body.dataset.bg = look.background || 'scene';
  bg.apply(look.background || 'scene');
  fonts.apply(look.fonts);
  if ((look.clock || 'digital') !== clockId) { clockId = look.clock || 'digital'; tick(); }
}

function applyPrefs({ relayout = false } = {}) {
  const p = st.prefs;
  applyLook(p);
  scene.configure({ react: p.weather_react, byTime: p.sky_by_time, fx: p.saver.fx });
  $('.scr-saver').classList.toggle('sv-clockless', !p.saver.clock);
  paintMe();
  if (relayout) W.renderZone('side', p.layout.side || [], { app, opts: p.widget_opts });
  const body = $('.scr-dash .body');
  keepFocus(body, renderServices);
  if (st.me) keepFocus(body, renderSystems);
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
const LAST = 'pvehomelab.last.' + SEAT;
const lastUser = () => { try { return localStorage.getItem(LAST) || ''; } catch { return ''; } };

function paintLoginChrome() {
  const L = st.pub.login || {};
  $('#loginTitle').textContent = L.title || '';
  $('#loginTitle').hidden = !L.title;
  $('.scr-login .date').hidden = L.date === false;
  $('.scr-login .host').hidden = L.hostline === false;
  $('#users').classList.toggle('small', L.avatars === 'small');
}

function renderUsers() {
  const users = st.pub.users;
  const L = st.pub.login || {};
  paintLoginChrome();
  if (st.selUser == null && L.remember_last !== false && users.some((u) => u.id === lastUser())) st.selUser = lastUser();
  if (!st.selUser && users.length) st.selUser = users[0].id;
  if (st.selUser === '' && L.other_user === false) st.selUser = users[0]?.id ?? '';
  $('#users').innerHTML = users.map((u, i) => {
    const av = avatar(u, u.avatar);
    return `<button class="user${u.id === st.selUser ? ' sel' : ''}" style="--i:${i + 4}" type="button" data-user="${esc(u.id)}">
      <span class="avw"><span class="av" style="background:${av.bg}">${av.inner}</span></span>
      <span class="nm">${esc(u.name)}</span><small>${esc(u.id)}</small></button>`;
  }).join('') + (L.other_user === false && users.length ? '' : `<button class="user${st.selUser === '' ? ' sel' : ''}" type="button" data-user="">
      <span class="avw"><span class="av" style="background:rgba(255,255,255,.08)"><svg viewBox="0 0 24 24"><use href="#i-user"/></svg></span></span>
      <span class="nm">${t('login.other')}</span><small>${t('login.other_sub')}</small></button>`);
  $$('[data-user]').forEach((b) => (b.onclick = () => selectUser(b.dataset.user)));
  selectUser(st.selUser ?? '', true);
}

function selectUser(id, initial = false) {
  st.selUser = id;
  $$('[data-user]').forEach((b) => b.classList.toggle('sel', b.dataset.user === id));
  const u = st.pub.users.find((x) => x.id === id);
  $('#otherRow').hidden = !!u;
  $('#pwLabel').textContent = u ? t('login.password_for', { user: u.id }) : t('login.password');
  $('#loginErr').hidden = true;
  applyLook(u || {});
  if (!initial) useLang();
  W.renderZone('login', u?.login?.length ? u.login : ['weather', 'host'], { app, opts: u?.widget_opts });
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
    try { localStorage.setItem(LAST, r.user); } catch {}
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
  await i18n.setLang(wantedLang());
  tabs.setLang(i18n.current());
  rerender();
  applyPrefs();
  W.stopZone('login');
  W.renderZone('side', prefs.layout.side || [], { app, opts: prefs.widget_opts });
  go('dash');
  weather(true).catch(() => {});
  await refreshDash();
  // Systems arrive after the screen is shown; land keyboard focus on the first one.
  const a = document.activeElement;
  if (st.screen === 'dash' && (!a || a === document.body || a.closest('.top'))) nav.focusFirst(undefined, '.sys .play');
  st.timers.push(setInterval(refreshDash, 10000));
  updReminded = false;
  setTimeout(checkUpdate, 2500);
  st.timers.push(setInterval(checkUpdate, 30 * 60000));
}

async function logout() {
  st.timers.splice(0).forEach(clearInterval);
  W.stopZone('side');
  try { await api.post('/api/logout'); } catch {}
  st.me = null; st.prefs = null;
  try { st.pub = await api.get('/api/public'); } catch {}
  await useLang();
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
  if (bad?.reason?.status === 401) { toast(t('dash.session_over'), true); logout(); }
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

let railUpdate = null;
function renderSystems() {
  const el = $('#systems');
  railUpdate ||= rail($('#sysrail'));
  requestAnimationFrame(railUpdate);
  const hidden = (st.prefs?.hidden_systems || []).map(String);
  st.sysView = arrange('systems', st.systems.filter((v) => !hidden.includes(String(v.vmid))), st.prefs || {});
  if (!st.sysView.length) {
    el.innerHTML = `<div class="glass empty">${esc(t('dash.no_systems', { tag: '«' + (st.pub.systems_tag || 'seat') + '»' }))}</div>`;
    return;
  }
  el.innerHTML = st.sysView.map((vm, i) => {
    const [, logo, art] = osOf(vm);
    const run = vm.status === 'running';
    return `<div class="sys" style="--i:${i}" draggable="true" data-drag="systems" data-key="${vm.vmid}"><div class="art" style="background:${art}"></div>
      <img class="os" src="/icons/${logo}.svg" alt="" draggable="false" style="${logo === 'apple' ? 'filter:invert(1)' : ''}" onerror="this.style.visibility='hidden'">
      <span class="state"><span class="dot ${run ? 'ok' : 'off'}"></span>${run ? t('sys.running', { time: fmt.uptime(vm.uptime) }) : vm.suspended ? t('sys.suspended') : t('sys.stopped')}</span>
      <h5 title="${esc(vm.name)}">${esc(vm.name)}</h5><div class="meta"><span>VM ${vm.vmid}</span><span>${t('cores', { n: vm.cores })} · ${t('gb', { n: Math.round(vm.memory / 1024) })}</span></div>
      <button class="play${run ? ' go' : ''}" type="button" data-sys="${i}" data-move="systems" data-key="${vm.vmid}" title="${esc(t(run ? 'sys.go' : 'sys.start', { name: vm.name }))}">
        <svg><use href="#${run ? 'i-arrow' : 'i-play'}"/></svg></button></div>`;
  }).join('');
  $$('[data-sys]').forEach((b) => (b.onclick = () => { lastSysBtn = b; openLaunch(st.sysView[+b.dataset.sys]); }));
}

function renderServices() {
  if (!st.prefs) return;
  const hidden = st.prefs.hidden_services || [];
  const q = st.filter.trim().toLowerCase();
  const visible = st.services.filter((s) => !hidden.includes(s.key));
  const list = arrange('services', visible, st.prefs)
    .filter((s) => !q || `${s.name} ${s.host} ${s.guest?.name || ''}`.toLowerCase().includes(q));
  $('#svcCount').textContent = visible.length;
  const down = st.services.filter((s) => s.status && s.status !== 'running');
  $('#health').classList.toggle('warn', down.length > 0);
  $('#health').title = down.length ? t('top.health_down', { list: down.map((s) => s.name).join(', ') }) : t('top.health_ok');
  const found = st.services.filter((s) => s.source === 'port' || s.source === 'notes').length;
  $('.ptabs .src span').textContent = t('svc.count', { caddy: st.services.filter((s) => s.source === 'caddy').length, found });
  if (!list.length) {
    $('#svcgrid').innerHTML = `<div class="mute" style="grid-column:1/-1;padding:1em">${esc(q ? t('search.none', { q: st.filter }) : t('dash.no_services'))}</div>`;
    return;
  }
  $('#svcgrid').innerHTML = list.map((s, i) => {
    const cls = s.status === 'running' ? '' : s.status ? ' down' : ' unknown';
    const gname = s.guest ? `${s.guest.type === 'lxc' ? 'CT' : s.guest.type === 'qemu' ? 'VM' : ''} ${s.guest.vmid || ''} ${s.guest.name || ''}`.trim() : '';
    const src = s.source === 'port' ? t('svc.src_port', { guest: gname, port: s.port })
      : s.source === 'notes' ? t('svc.src_notes', { guest: gname })
      : s.source === 'link' ? t('svc.src_link') : t('svc.src_caddy', { host: s.upstream || s.host });
    return `<button type="button" class="svc${cls}" style="--i:${i + 3}" draggable="${q ? 'false' : 'true'}" data-drag="services" data-move="services" data-key="${esc(s.key)}"
      data-url="${esc(s.url)}" title="${esc([s.desc, src].filter(Boolean).join('\n'))}">
      <span class="st"></span><span class="lg"><img src="/icons/${esc(s.icon || s.key)}.svg" alt="" draggable="false"
        onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'letter',textContent:'${esc(s.name[0])}'}))"></span>
      <span class="n">${esc(s.name)}</span><small>${esc(s.host)}</small></button>`;
  }).join('');
  $$('#svcgrid [data-url]').forEach((b) => (b.onclick = () => app.openUrl(b.dataset.url)));
}

/* ---------------- ordering: drag with the mouse, Alt+←/→ with the keyboard ---------------- */
async function saveOrder(kind, keys) {
  if (!keys) return;
  st.prefs.order = { ...(st.prefs.order || {}), [kind]: keys };
  st.prefs.sort = { ...(st.prefs.sort || {}), [kind]: 'manual' };
  const body = $('.scr-dash .body');
  keepFocus(body, kind === 'systems' ? renderSystems : renderServices);
  try { await api.put('/api/prefs', st.prefs); } catch (e) { toast(e.message, true); }
}
app.saveOrder = saveOrder;

const listOf = (kind) => (kind === 'systems' ? st.systems : st.services);
let dragKey = null, dragKind = null;
addEventListener('dragstart', (e) => {
  const el = e.target.closest?.('[data-drag]');
  if (!el) return;
  dragKey = el.dataset.key; dragKind = el.dataset.drag;
  el.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragKey);
});
addEventListener('dragover', (e) => {
  const el = e.target.closest?.('[data-drag]');
  if (!el || el.dataset.drag !== dragKind) return;
  e.preventDefault();
  $$('.drop-before').forEach((x) => x !== el && x.classList.remove('drop-before'));
  el.classList.add('drop-before');
});
addEventListener('drop', (e) => {
  const el = e.target.closest?.('[data-drag]');
  if (!el || el.dataset.drag !== dragKind) return;
  e.preventDefault();
  if (el.dataset.key !== dragKey) saveOrder(dragKind, moved(dragKind, listOf(dragKind), st.prefs, dragKey, { beforeKey: el.dataset.key }));
});
addEventListener('dragend', () => {
  $$('.dragging, .drop-before').forEach((x) => x.classList.remove('dragging', 'drop-before'));
  dragKey = dragKind = null;
});
addEventListener('keydown', (e) => {
  if (st.screen !== 'dash' || !e.altKey || e.ctrlKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
  const el = document.activeElement?.closest?.('[data-move]');
  if (!el || st.filter) return;
  e.preventDefault();
  const delta = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1;
  saveOrder(el.dataset.move, moved(el.dataset.move, listOf(el.dataset.move), st.prefs, el.dataset.key, { delta }));
});

/* ---------------- search: just start typing on the dashboard ---------------- */
function setFilter(v) {
  st.filter = v;
  const box = $('#svcSearch');
  box.hidden = !v;
  if (box.value !== v) box.value = v;
  if (v) $$('[data-ptab]').forEach((x) => x.setAttribute('aria-selected', x.dataset.ptab === 'web')), $$('[data-pane]').forEach((p) => (p.hidden = p.dataset.pane !== 'web'));
  renderServices();
}
$('#svcSearch').addEventListener('input', (e) => setFilter(e.target.value));
$('#svcSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.stopPropagation(); setFilter(''); nav.focusFirst(undefined, '#svcgrid .svc'); }
  if (e.key === 'Enter') { const first = $('#svcgrid .svc'); if (first) first.click(); }
});
addEventListener('keydown', (e) => {
  if (st.screen !== 'dash' || e.ctrlKey || e.altKey || e.metaKey || e.key.length !== 1 || e.key === ' ' || e.key === '?') return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
  const box = $('#svcSearch');
  box.hidden = false;
  box.focus(); // the key lands in the search box
}, true);

function renderGuests() {
  $('#guestCount').textContent = st.guests.length;
  const svcBy = {};
  st.services.forEach((s) => { if (s.guest) (svcBy[s.guest.vmid] ||= s); });
  $('#guestrows').innerHTML = st.guests.map((g) => {
    const run = g.status === 'running', svc = svcBy[g.vmid];
    const logo = svc ? `<img src="/icons/${esc(svc.icon)}.svg" alt="" onerror="this.style.visibility='hidden'">` : `<span class="gen">${icon('i-box')}</span>`;
    return `<tr><td class="nm"><span>${logo}${esc(g.name)}</span></td><td>${g.vmid}</td><td><span class="type">${g.type === 'qemu' ? 'VM' : 'CT'}</span></td>
      <td>${run ? `<span class="stp"><span class="dot ok"></span>${t('guest.running')}</span>` : `<span class="stp mute"><span class="dot off"></span>${t('guest.stopped')}</span>`}</td>
      <td>${run ? fmt.pct((g.cpu || 0) * 100) : '—'}</td><td>${run ? fmt.bytes(g.mem) : '—'}</td>
      <td>${svc ? `<button class="lnk" type="button" data-url="${esc(svc.url)}">${esc(svc.key)} ${icon('i-ext')}</button>` : ''}</td>
      <td><div class="acts"><button type="button" data-act="${g.type}|${g.vmid}|${run ? 'shutdown' : 'start'}|${esc(g.name)}" title="${t(run ? 'guest.shutdown' : 'guest.start')}">${icon(run ? 'i-stop' : 'i-start')}</button>
        ${run ? `<button type="button" data-act="${g.type}|${g.vmid}|reboot|${esc(g.name)}" title="${t('guest.reboot')}">${icon('i-restart')}</button>` : ''}
        <button type="button" data-console="${g.type}|${g.vmid}|${esc(g.name)}" title="${t('guest.console')}">${icon('i-term')}</button></div></td></tr>`;
  }).join('');
  $$('#guestrows [data-url]').forEach((b) => (b.onclick = () => app.openUrl(b.dataset.url)));
  $$('#guestrows [data-console]').forEach((b) => (b.onclick = () => {
    const [t, id, name] = b.dataset.console.split('|');
    app.openUrl(`${app.pveUrl()}/?console=${t === 'qemu' ? 'kvm' : 'lxc'}&novnc=1&vmid=${id}&vmname=${encodeURIComponent(name)}&node=${st.pub.node}`);
  }));
  $$('#guestrows [data-act]').forEach((b) => (b.onclick = async () => {
    const [t, id, act, name] = b.dataset.act.split('|');
    if (act !== 'start') {
      const r = act === 'reboot';
      const ok = await confirmBox(t(r ? 'guest.confirm_reboot' : 'guest.confirm_shutdown', { name }),
        t(r ? 'guest.confirm_reboot_text' : 'guest.confirm_shutdown_text'), t(r ? 'guest.reboot' : 'guest.shutdown'));
      if (!ok) return;
    }
    try { await api.post(`/api/guests/${t}/${id}/${act}`); toast(t('guest.sent', { name })); setTimeout(refreshDash, 1500); }
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
          else { $('#mCancel').textContent = t('launch.close'); setTimeout(() => { if (st.screen === 'launch') go('dash'); refreshDash(); }, 2500); }
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

/* ---------------- updates ---------------- */
let upd = null, updReminded = false;
const updLabel = (u) => u.latest.version ? `v${u.latest.version}` : (u.latest.commit || '').slice(0, 7);

async function checkUpdate() {
  if (!st.me) return;
  try { upd = await api.get('/api/update'); } catch { upd = null; }
  const pill = $('#updPill');
  pill.hidden = !upd?.available;
  if (!upd?.available) return;
  pill.querySelector('span').textContent = t('upd.pill', { v: updLabel(upd) });
  pill.title = upd.latest.notes || '';
  // Remind once per sign-in.
  if (!updReminded) { updReminded = true; toast(t('upd.remind', { v: updLabel(upd) })); }
}

$('#updPill').onclick = async () => {
  if (!upd?.available) return;
  const v = updLabel(upd);
  if (!upd.can_apply) { toast(t('upd.no_perm', { v }), true); return; }
  if (!(await confirmBox(t('upd.confirm_title', { v }), t('upd.confirm_text'), t('upd.apply')))) return;
  try { await api.post('/api/update/apply'); toast(t('upd.started')); $('#updPill').hidden = true; }
  catch (e) { toast(e.message, true); }
};

/* ---------------- open service tabs ---------------- */
function renderOpenTabs(list) {
  const el = $('#openTabs');
  keepFocus(el, () => {
    el.innerHTML = list.map((tab) => `
      <span class="otab"><button class="go" type="button" data-tab="${tab.id}" title="${esc(tab.url)}">
        ${tab.icon ? `<img src="${esc(tab.icon)}" alt="">` : icon('i-ext')}<span>${esc(tab.title)}</span></button>
        <button class="x" type="button" data-tabx="${tab.id}" title="${esc(t('tabs.close', { name: tab.title }))}">${icon('i-x')}</button></span>`).join('');
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
  $$('[data-clock]').forEach((e) => clocks.paint(e, clockId, d, i18n.locale()));
  $$('[data-date]').forEach((e) => (e.textContent = d.toLocaleDateString(i18n.locale(), { weekday: 'long', day: 'numeric', month: 'long' })));
}

/* ---------------- keyboard help (?) ---------------- */
const HELP = [
  ['help.k_nav', '← → ↑ ↓'], ['help.k_tab', 'Tab · Shift+Tab'], ['help.k_open', 'Enter'], ['help.k_back', 'Esc'],
  ['help.k_search', 'a…z'], ['help.k_move', 'Alt + ← →'], ['help.k_dock', 'Alt+Q'], ['help.k_console', 'Ctrl+Alt+Q'],
  ['help.k_help', '?'],
];
function showHelp() {
  $('#helpTable').innerHTML = HELP.map(([k, keys]) => `<tr><td>${esc(t(k))}</td><td><span class="kbd">${esc(keys)}</span></td></tr>`).join('');
  $('#helpLayer').hidden = false;
  $('#helpClose').focus();
}
const hideHelp = () => { $('#helpLayer').hidden = true; };
$('#helpClose').onclick = hideHelp;
addEventListener('keydown', (e) => {
  if (e.key === '?' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName) && st.screen !== 'console') { e.preventDefault(); showHelp(); }
  else if (e.key === 'Escape' && !$('#helpLayer').hidden) { e.stopImmediatePropagation(); hideHelp(); }
}, true);

/* ---------------- about ---------------- */
let about = {};
function paintAbout() {
  const v = st.pub?.app?.version;
  const who = about.author ? t('about.by', { name: about.author }) : '';
  $$('[data-about]').forEach((el) => {
    el.innerHTML = `<b>${esc(about.name || 'PVE Homelab')}</b>${v ? ` <span>v${esc(v)}</span>` : ''}${who ? ` · ${esc(who)}` : ''}`
      + ` · <button type="button" class="linklike" data-help>${esc(t('help.short'))}</button>`;
  });
  $$('[data-help]').forEach((b) => (b.onclick = showHelp));
}
app.about = () => about;

/* ---------------- boot ---------------- */
async function boot() {
  errlog.init();
  scene.init();
  nav.init();
  st.pub = await api.get('/api/public');
  for (const t of st.pub.themes) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = `/themes/${t.id}.css`;
    document.head.appendChild(l);
  }
  bg.init(st.pub.backgrounds);
  fonts.init(st.pub.fonts);
  $$('[data-seat-name]').forEach((x) => (x.textContent = st.pub.seat.gpu_name));
  $$('[data-hostline]').forEach((x) => (x.textContent = `${st.pub.node} · Proxmox VE ${st.pub.version} · ${st.pub.ip}`));
  $$('[data-node]').forEach((x) => (x.textContent = st.pub.node));
  try { about = await (await fetch('/about.json', { cache: 'no-cache' })).json(); } catch {}
  if (st.pub.demo) {
    document.body.classList.add('demo');
    const { initDemo } = await import('./demo-panel.js');
    initDemo(app, { refresh: () => refreshDash(), weather: () => weather(true) });
  }
  S.init(app);
  tabs.watch(renderOpenTabs);
  await W.load(st.pub.widgets);
  await useLang();
  tick(); setInterval(tick, 1000);
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
  errlog.report('boot', e.message, e.stack);
  toast(t('error.load', { msg: e.message }), true);
  setTimeout(() => location.reload(), 5000);
});
