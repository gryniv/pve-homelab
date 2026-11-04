// PVE Homelab front end: screens, login, dashboard, launching systems.

import { api, SEAT } from './api.js';
import * as scene from './scene.js';
import * as W from './widgets.js';
import * as S from './settings.js';
import * as nav from './nav.js';
import * as vnc from './console.js';
import * as tabs from './tabs.js';
import { arrange } from './order.js';
import { rail } from './rail.js';
import * as bg from './backgrounds.js';
import * as clocks from './clocks.js';
import * as fonts from './fonts.js';
import * as errlog from './errlog.js';
import * as i18n from './i18n.js';
import * as help from './help.js';
import * as feedback from './feedback.js';
import * as alerts from './alerts.js';
import * as updates from './updates.js';
import * as nodeUpdates from './nodeupdates.js';
import * as designer from './designer.js';
import * as showcase from './showcase.js';
import * as launch from './launch.js';
import * as guests from './guests.js';
import * as dnd from './dnd.js';
import * as search from './search.js';
import { st } from './state.js';
import { $, $$, icon, esc, avatar, fmt, toast, keepFocus, t, wxIcon, kindLabel } from './ui.js';

/* ---------------- app facade given to widgets & settings ---------------- */
const app = {
  api, go,
  pub: () => st.pub,
  seat: () => st.pub.seat,
  prefs: () => st.prefs || {},
  me: () => st.me,
  isAdmin: () => !!st.admin,
  loggedIn: () => !!st.me,
  services: () => st.services,
  systems: () => st.systems,
  updateStatus: () => updates.status(),
  nodeUpdatesAllowed: () => nodeUpdates.allowed(),
  showNodeUpdates: (from) => nodeUpdates.show(from),
  showHelp: () => help.show(),
  showFeedback: (from) => feedback.show(from),
  isNight: scene.isNight,
  avatarOf: (u) => avatar(u, u.avatar ?? st.prefs?.avatar),
  guestCounts: () => st.pub.guests,
  openSettings: (s, tab) => { S.open(s, tab); go('settings'); },
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
  updates.paint(); nodeUpdates.paint();
  if (st.me) {
    W.renderZone('side', st.prefs.layout.side || [], { app, opts: st.prefs.widget_opts });
    const body = $('.scr-dash .body');
    keepFocus(body, renderSystems); keepFocus(body, renderServices); keepFocus(body, guests.render);
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
  const src = wxIcon(w.kind, night);
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
  nodeUpdates.paint();
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
    else if (screen === 'dash' && prev === 'launch' && launch.lastButton()?.isConnected) launch.lastButton().focus();
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
    await enter(r.user, r.prefs, r.admin);
  } catch (err) {
    $('#loginErr').textContent = err.message;
    $('#loginErr').hidden = false;
    $('#pw').select();
  } finally { btn.disabled = false; }
});

async function enter(userid, prefs, admin = false) {
  const u = st.pub.users.find((x) => x.id === userid) || { id: userid, name: userid.split('@')[0] };
  st.me = { ...u };
  st.prefs = prefs;
  st.admin = admin;
  await i18n.setLang(wantedLang());
  tabs.setLang(i18n.current());
  rerender();
  applyPrefs();
  W.stopZone('login');
  W.renderZone('side', prefs.layout.side || [], { app, opts: prefs.widget_opts });
  go('dash');
  reopenSettings();
  weather(true).catch(() => {});
  await refreshDash();
  // Systems arrive after the screen is shown; land keyboard focus on the first one.
  const a = document.activeElement;
  if (st.screen === 'dash' && (!a || a === document.body || a.closest('.top'))) nav.focusFirst(undefined, '.sys .play');
  st.timers.push(setInterval(refreshDash, 10000));
  updates.resetReminder();
  setTimeout(updates.check, 2500);
  setTimeout(alerts.check, 1500);
  setTimeout(nodeUpdates.check, 3500);
  st.timers.push(setInterval(alerts.check, 60000));
  st.timers.push(setInterval(updates.check, 30 * 60000));
  st.timers.push(setInterval(nodeUpdates.check, 30 * 60000));
}

// Installing or removing a design reloads the page (new stylesheets, new lists); it asks to come
// back to the same settings tab through sessionStorage.
function reopenSettings() {
  let want = null;
  try { want = sessionStorage.getItem('pvehomelab.reopen'); sessionStorage.removeItem('pvehomelab.reopen'); } catch {}
  if (!want) return;
  const [section, tab] = want.split(':');
  app.openSettings(section, tab);
}

async function logout() {
  st.timers.splice(0).forEach(clearInterval);
  launch.stop();
  W.stopZone('side');
  try { await api.post('/api/logout'); } catch {}
  // The next person must not see this one's systems, services or guests while theirs load.
  st.systems = []; st.services = []; st.guests = []; st.sysView = [];
  if (st.filter) search.setFilter('');
  renderSystems(); renderServices(); guests.render();
  alerts.reset();
  nodeUpdates.reset();
  guests.reset();
  st.admin = false;
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
  if (gst.status === 'fulfilled') { st.guests = gst.value; keepFocus(body, guests.render); }
  const bad = [sys, svc, gst].find((r) => r.status === 'rejected');
  if (bad?.reason?.status === 401) { toast(t('dash.session_over'), true); logout(); }
}

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
    const [, logo, art] = launch.osOf(vm);
    const run = vm.status === 'running';
    return `<div class="sys" style="--i:${i}" draggable="true" data-drag="systems" data-key="${vm.vmid}"><div class="art" style="background:${art}"></div>
      <img class="os" src="/icons/${logo}.svg" alt="" draggable="false" style="${logo === 'apple' ? 'filter:invert(1)' : ''}" onerror="this.style.visibility='hidden'">
      <span class="state"><span class="dot ${run ? 'ok' : 'off'}"></span>${run ? t('sys.running', { time: fmt.uptime(vm.uptime) }) : vm.suspended ? t('sys.suspended') : t('sys.stopped')}</span>
      <h5 title="${esc(vm.name)}">${esc(vm.name)}</h5><div class="meta"><span>VM ${vm.vmid}</span><span>${t('cores', { n: vm.cores })} · ${t('gb', { n: Math.round(vm.memory / 1024) })}</span></div>
      <button class="play${run ? ' go' : ''}" type="button" data-sys="${i}" data-move="systems" data-key="${vm.vmid}" title="${esc(t(run ? 'sys.go' : 'sys.start', { name: vm.name }))}">
        <svg><use href="#${run ? 'i-arrow' : 'i-play'}"/></svg></button></div>`;
  }).join('');
  $$('[data-sys]').forEach((b) => (b.onclick = () => launch.open(st.sysView[+b.dataset.sys], b)));
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
    const gname = s.guest ? `${kindLabel(s.guest.type)} ${s.guest.vmid || ''} ${s.guest.name || ''}`.trim() : '';
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

/* ---------------- ordering: drag with the mouse, Alt+←/→ with the keyboard (dnd.js) ---------------- */
dnd.init({ renderSystems, renderServices });
app.saveOrder = dnd.saveOrder;

/* ---------------- search: just start typing on the dashboard (search.js) ---------------- */
search.init({ renderServices });

/* ---------------- containers & VMs table (guests.js) ---------------- */
guests.init({ openUrl: (u) => app.openUrl(u), pveUrl: () => app.pveUrl(), openConsole, refreshDash });

$$('[data-ptab]').forEach((b) => (b.onclick = () => {
  $$('[data-ptab]').forEach((x) => x.setAttribute('aria-selected', x === b));
  $$('[data-pane]').forEach((p) => (p.hidden = p.dataset.pane !== b.dataset.ptab));
}));

/* ---------------- launch (launch.js) ---------------- */
launch.init({ go, refreshDash, openConsole });

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
async function openConsole(vm, fallback) {
  go('console');
  try {
    await vnc.open(api, vm, (msg) => { if (st.screen === 'console') { toast(msg); go('dash'); refreshDash(); } });
  } catch (e) {
    go('dash');
    // No rights is the answer; anything else (no console here, the demo) may still work in the Proxmox UI.
    if (fallback && e.status !== 403) fallback();
    else toast(e.message, true);
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

/* ---------------- keyboard help, alerts, updates: their own modules ---------------- */
help.init(() => st.screen);
feedback.init();
alerts.init();
updates.init();
nodeUpdates.init(app);

/* ---------------- about ---------------- */
let about = {};
function paintAbout() {
  const v = st.pub?.app?.version;
  const who = about.author ? t('about.by', { name: about.author }) : '';
  $$('[data-about]').forEach((el) => {
    el.innerHTML = `<b>${esc(about.name || 'PVE Homelab')}</b>${v ? ` <span>v${esc(v)}</span>` : ''}${who ? ` · ${esc(who)}` : ''}`
      + ` · <button type="button" class="linklike" data-help>${esc(t('help.short'))}</button>`;
  });
  $$('[data-help]').forEach((b) => (b.onclick = help.show));
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
  await W.load(st.pub.widgets, st.pub.widget_styles || []);
  await useLang();
  designer.init(st.pub);
  // ?showcase=<kind>:<id> shows one design in every state (see showcase.js); the menu runs underneath
  const sc = new URLSearchParams(location.search).get('showcase');
  if (sc) showcase.open(sc, st.pub);
  tick(); setInterval(tick, 1000);
  weather().catch(() => {});
  setInterval(() => weather(true).catch(() => {}), 900000);
  setInterval(async () => { try { const p = await api.get('/api/public'); st.pub.guests = p.guests; } catch {} }, 30000);
  try {
    const me = await api.get('/api/me');
    await enter(me.user, me.prefs, me.admin);
  } catch {
    renderUsers();
    go('login');
  }
}

boot().catch((e) => {
  errlog.report('boot', e.message, e.stack);
  // The dictionary may be what failed to load: never show the bare key.
  const text = t('error.load', { msg: e.message });
  toast(text === 'error.load' ? `Failed to load: ${e.message}` : text, true);
  setTimeout(() => location.reload(), 5000);
});
