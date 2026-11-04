// PVE Homelab front end: screens, login, dashboard, launching systems.

import { api, SEAT, setSeat } from './api.js';
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
import * as gamepad from './gamepad.js';
import * as showcase from './showcase.js';
import * as launch from './launch.js';
import * as guests from './guests.js';
import * as dnd from './dnd.js';
import * as search from './search.js';
import { st } from './state.js';
import { $, $$, icon, esc, avatar, fmt, toast, keepFocus, t, wxIcon, kindLabel, setToastTime } from './ui.js';

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
  checkUpdate: () => updates.checkNow(),
  feature: (name) => feature(name),
  // after Settings → System changed something the page shows (components switched off, say)
  refreshPub: async () => { st.pub = await api.get('/api/public'); paintPub(); W.renderZone('side', st.prefs.layout.side || [], { app, opts: st.prefs.widget_opts }); },
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
// A browser elsewhere isn't a monitor of this host: it says so instead of naming a GPU.
const paintSeat = () => st.pub && $$('[data-seat-name]').forEach((x) => (x.textContent = st.pub.seat.remote ? t('seat.web') : st.pub.seat.gpu_name));

function rerender() {
  tick(); paintWeather(); renderLoginLang(); paintAbout(); paintSeat();
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
  if (!feature('weather')) return null;
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

// A theme's own settings (its @option lines) land on the page as data-o-<key>; its CSS reads them
// under its own [data-skin]. Unset or unknown values fall back to the theme's default.
function applyThemeOpts(skin, chosen = {}) {
  const b = document.body;
  [...b.attributes].filter((a) => a.name.startsWith('data-o-')).forEach((a) => b.removeAttribute(a.name));
  const th = st.pub?.themes?.find((x) => x.id === skin);
  (th?.options || []).forEach((o) => b.setAttribute(`data-o-${o.key}`, o.values.includes(chosen[o.key]) ? chosen[o.key] : o.default));
}

// A theme or background removed since someone chose it: the built-in default stands in, quietly
// (clocks.js does the same for a clock).
function applyLook(look = {}) {
  const has = (list, id) => !!id && (!list || list.some((x) => x.id === id));
  const skin = has(st.pub?.themes, look.skin) ? look.skin : 'dusk';
  const back = has(bg.all(), look.background) ? look.background : 'scene';
  document.body.dataset.skin = skin;
  applyThemeOpts(skin, look.theme_opts?.[skin]);
  document.body.dataset.bg = back;
  bg.apply(back);
  fonts.apply(look.fonts);
  if ((look.clock || 'digital') !== clockId) { clockId = look.clock || 'digital'; tick(); }
}

// Settings → Interface: size, calm, hours, date, which parts of the dashboard show, toasts.
function applyUi(ui) {
  document.documentElement.style.setProperty('--ui-scale', String((ui.scale || 100) / 100));
  document.body.classList.toggle('calm', ui.motion === 'calm');
  for (const k of ['systems', 'web', 'guests']) document.body.classList.toggle('no-' + k, ui.sections?.[k] === false);
  if (ui.sections?.web === false && ui.sections?.guests !== false) $('[data-ptab=guests]')?.click();
  clocks.setHours(ui.clock);
  setToastTime(ui.toast_sec);
  st.dateStyle = ui.date;
  tick();
}

function applyPrefs({ relayout = false } = {}) {
  const p = st.prefs;
  applyLook(p);
  applyUi(p.ui || {});
  scene.configure({ react: p.weather_react, byTime: p.sky_by_time, fx: p.saver.fx && p.ui?.motion !== 'calm' });
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
  scene.fxRun(screen !== 'console' && screen !== 'away');
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
// What /api/public says about the host; a browser elsewhere gets less before signing in.
function paintPub() {
  const p = st.pub;
  $$('[data-hostline]').forEach((x) => (x.textContent = [p.node, p.version && `Proxmox VE ${p.version}`, p.ip].filter(Boolean).join(' · ')));
  $$('[data-node]').forEach((x) => (x.textContent = p.node));
  W.setHostFigures(p.stats);
  W.setFeatures(p.features);
  // What is switched off on this host (Settings → System → Components) leaves the page.
  const off = Object.entries(p.features || {}).filter(([, on]) => on === false).map(([k]) => k);
  let style = $('#featuresOff');
  if (!style) { style = document.createElement('style'); style.id = 'featuresOff'; document.head.appendChild(style); }
  style.textContent = off.map((f) => `[data-needs~="${f}"]{display:none!important}`).join('\n');
}
const feature = (name) => st.pub?.features?.[name] !== false;

// Per seat; the seat is known once /api/public has answered (setSeat), hence a function.
const lastKey = () => 'pvehomelab.last.' + SEAT;
const lastUser = () => { try { return localStorage.getItem(lastKey()) || ''; } catch { return ''; } };

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
  // No people listed (a browser elsewhere): the name typed last time is the likely one.
  if (!users.length && !$('#otherUser').value && L.remember_last !== false) $('#otherUser').value = lastUser();
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
  if (tfa && !initial) { tfa = null; paintTfa(false); }
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

/* the second factor: after the password, Proxmox may want a code (TOTP), a recovery key or a YubiKey */
const TFA_LEAD = { totp: 'login.tfa_totp', recovery: 'login.tfa_recovery', yubico: 'login.tfa_yubico' };
const TFA_USE = { totp: 'login.tfa_use_totp', recovery: 'login.tfa_use_recovery', yubico: 'login.tfa_use_yubico' };
let tfa = null;   // {id, methods, kind} while the code is asked

function paintTfa(focus = true) {
  const on = !!tfa;
  $('#loginForm').classList.toggle('tfa-on', on);
  $('#tfaBox').hidden = !on;
  if (!on) return;
  const code = $('#tfaCode');
  const digits = tfa.kind === 'totp';
  $('#tfaLead').textContent = t(TFA_LEAD[tfa.kind]);
  code.value = '';
  code.classList.toggle('key', !digits);
  code.inputMode = digits ? 'numeric' : 'text';
  code.maxLength = digits ? 6 : 128;
  code.placeholder = digits ? '••••••' : '';
  $('#tfaPad').hidden = !digits;
  $('#tfaOther').innerHTML = tfa.methods.filter((m) => m !== tfa.kind && TFA_USE[m])
    .map((m) => `<button type="button" class="chipbtn" data-tfa-kind="${m}">${esc(t(TFA_USE[m]))}</button>`).join('');
  $$('[data-tfa-kind]').forEach((b) => (b.onclick = () => { tfa.kind = b.dataset.tfaKind; $('#loginErr').hidden = true; paintTfa(); }));
  if (focus) (digits ? $('#tfaPad [data-k="1"]') : code).focus();
}

function startTfa(ch) {
  if (!ch.methods.length) {   // only a security key: that works in the Proxmox web UI alone
    $('#loginErr').textContent = t('login.tfa_webauthn');
    $('#loginErr').hidden = false;
    return;
  }
  tfa = { id: ch.id, methods: ch.methods, kind: ch.methods.includes('totp') ? 'totp' : ch.methods[0] };
  $('#loginErr').hidden = true;
  paintTfa();
}

function leaveTfa(message) {
  tfa = null;
  paintTfa(false);
  $('#loginErr').textContent = message || '';
  $('#loginErr').hidden = !message;
  (st.selUser ? $('#pw') : $('#otherUser')).focus();
}

function typeDigit(k) {
  const code = $('#tfaCode');
  if (k === 'del') code.value = code.value.slice(0, -1);
  else if (code.value.length < 6) code.value += k;
  if (code.value.length === 6) $('#loginForm').requestSubmit();
}

$$('#tfaPad [data-k]').forEach((b) => (b.onclick = () => typeDigit(b.dataset.k)));
$('#tfaCode').addEventListener('input', (e) => {
  if (tfa?.kind !== 'totp') return;
  e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
  if (e.target.value.length === 6) $('#loginForm').requestSubmit();
});
$('#tfaBack').onclick = () => leaveTfa();
$('#loginForm').addEventListener('keydown', (e) => {
  if (!tfa) return;
  if (e.key === 'Escape') { e.preventDefault(); leaveTfa(); return; }
  // digit keys work while the keypad has the focus, as on a remote with numbers
  if (tfa.kind === 'totp' && document.activeElement !== $('#tfaCode') && /^[0-9]$/.test(e.key)) { e.preventDefault(); typeDigit(e.key); }
  if (tfa.kind === 'totp' && document.activeElement !== $('#tfaCode') && e.key === 'Backspace') { e.preventDefault(); typeDigit('del'); }
});

async function submitTfa() {
  const code = $('#tfaCode').value.trim();
  if (!code) { $('#tfaCode').focus(); return; }
  try {
    const r = await api.post('/api/login/tfa', { id: tfa.id, kind: tfa.kind, code });
    try { localStorage.setItem(lastKey(), r.user); } catch {}
    tfa = null;
    paintTfa(false);
    await enter(r.user, r.prefs, r.admin);
  } catch (err) {
    // the challenge is gone (too slow, too many wrong codes, too many tries here): back to the password
    if ([404, 410, 429].includes(err.status)) return leaveTfa(err.message);
    $('#loginErr').textContent = err.message;
    $('#loginErr').hidden = false;
    $('#tfaCode').value = '';
    (tfa.kind === 'totp' ? $('#tfaPad [data-k="1"]') : $('#tfaCode')).focus();
  }
}

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (tfa) {
    const btn = $('#tfaPad .ok');
    btn.disabled = true;
    try { await submitTfa(); } finally { btn.disabled = false; }
    return;
  }
  const user = st.selUser || $('#otherUser').value.trim();
  if (!user) { $('#otherUser').focus(); return; }
  const btn = $('#loginBtn');
  btn.disabled = true;
  try {
    const r = await api.post('/api/login', { user, password: $('#pw').value });
    $('#pw').value = '';
    if (r.tfa) { startTfa(r.tfa); return; }
    try { localStorage.setItem(lastKey(), r.user); } catch {}
    await enter(r.user, r.prefs, r.admin);
  } catch (err) {
    $('#loginErr').textContent = err.message;
    $('#loginErr').hidden = false;
    $('#pw').select();
  } finally { btn.disabled = false; }
});

async function enter(userid, prefs, admin = false) {
  // Signed in, /api/public tells more (the people, host figures, versions) than before.
  try { st.pub = await api.get('/api/public'); paintPub(); } catch {}
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
  go(st.awayVm ? 'away' : 'dash');
  reopenSettings();
  weather(true).catch(() => {});
  await refreshDash();
  // Systems arrive after the screen is shown; land keyboard focus on the first one.
  const a = document.activeElement;
  if (st.screen === 'dash' && (!a || a === document.body || a.closest('.top'))) nav.focusFirst(undefined, '.sys .play');
  st.timers.push(setInterval(refreshDash, 10000));
  updates.resetReminder();
  if (feature('app_updates')) { setTimeout(updates.check, 2500); st.timers.push(setInterval(updates.check, 30 * 60000)); }
  if (feature('alerts')) { setTimeout(alerts.check, 1500); st.timers.push(setInterval(alerts.check, 60000)); }
  if (feature('node_updates')) { setTimeout(nodeUpdates.check, 3500); st.timers.push(setInterval(nodeUpdates.check, 30 * 60000)); }
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
  try { st.pub = await api.get('/api/public'); clocks.init(st.pub.clocks); paintPub(); } catch {}
  await useLang();
  renderUsers();
  go(st.awayVm ? 'away' : 'login');
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
  if (e.key === 'Escape' && st.screen === 'settings' && S.back()) return;   // out of a design folder first
  if (e.key === 'Escape' && ['settings', 'launch'].includes(st.screen)) go('dash');
});

$$('[data-go]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); go(b.dataset.go); }));

setInterval(() => {
  const idle = (Date.now() - st.lastInput) / 60000;
  if (st.screen === 'login' && idle >= st.pub.saver_after_min) go('saver');   // never while away
  if (st.me && st.pub.lock_after_min && idle >= st.pub.lock_after_min && st.screen !== 'launch') logout();
}, 10000);

/* ---------------- away: this seat's monitor shows a system (seats.py, /api/seat/events) ---------------- */
// While away the page acts on nothing but both Ctrl keys (back to the menu); from the menu, both
// Ctrl keys go to the system running on a GPU wired to this monitor.
let activitySent = 0;
function touched() {
  if (st.pub?.seat?.remote || !st.pub?.seat?.gpu) return;
  const dark = document.body.classList.contains('blank');
  if (!dark && Date.now() - activitySent < 20000) return;
  activitySent = Date.now();
  document.body.classList.remove('blank');
  api.post('/api/seat/activity').catch(() => {});
}
['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach((ev) => addEventListener(ev, touched, { passive: true, capture: true }));

function onSeat(state) {
  document.body.classList.toggle('blank', state.screen === 'off');
  if (state.shows !== 'menu') {
    st.awayVm = state.shows;
    const vm = st.systems.find((s) => s.vmid === state.shows);
    $('#awayName').textContent = vm ? vm.name : `VM ${state.shows}`;
    if (st.screen !== 'away') {
      launch.stop();
      W.stopZone('side');
      W.stopZone('login');
      go('away');
    }
  } else if (st.awayVm) {
    st.awayVm = null;
    if (st.me) {
      go('dash');
      W.renderZone('side', st.prefs.layout.side || [], { app, opts: st.prefs.widget_opts });
      refreshDash();
    } else {
      go('login');
      renderUsers();
    }
  }
}

function watchSeat() {
  if (st.pub.seat.remote || !st.pub.seat.gpu || !window.EventSource) return;
  const es = new EventSource('/api/seat/events?seat=' + encodeURIComponent(SEAT));
  es.onmessage = (e) => { try { onSeat(JSON.parse(e.data)); } catch {} };
  // a page going away lets go of its stream at once (or a few reloads use up the browser's connections)
  addEventListener('pagehide', () => es.close());
}

const ctrls = new Set();
let bothFired = false;
async function bothCtrl() {
  try {
    if (st.screen === 'away') await api.post('/api/seat/focus', { to: 'menu' });
    else if (st.me && !st.pub.seat.remote) await api.post('/api/seat/focus', { to: 'vm' });
  } catch (e) { if (st.screen !== 'away') toast(e.message, e.status >= 500); }
}
addEventListener('keydown', (e) => {
  if (e.code === 'ControlLeft' || e.code === 'ControlRight') {
    ctrls.add(e.code);
    if (ctrls.size === 2 && !bothFired) { bothFired = true; bothCtrl(); }
  }
  if (st.screen === 'away') { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
addEventListener('keyup', (e) => {
  ctrls.delete(e.code);
  if (!ctrls.size) bothFired = false;
  if (st.screen === 'away') { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
addEventListener('blur', () => { ctrls.clear(); bothFired = false; });

function tick() {
  const d = new Date();
  $$('[data-clock]').forEach((e) => clocks.paint(e, clockId, d, i18n.locale()));
  const date = st.dateStyle === 'iso' ? d.toLocaleDateString('sv-SE')
    : d.toLocaleDateString(i18n.locale(), st.dateStyle === 'short' ? { day: 'numeric', month: 'short', year: 'numeric' } : { weekday: 'long', day: 'numeric', month: 'long' });
  $$('[data-date]').forEach((e) => (e.textContent = date));
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
  clocks.init(st.pub.clocks);
  setSeat(st.pub.seat.id);
  document.body.classList.toggle('remote', !!st.pub.seat.remote);
  paintSeat();
  paintPub();
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
  watchSeat();
  gamepad.init({
    screen: () => st.screen,
    seatSwitch: () => bothCtrl(),
    openSettings: () => (st.me ? go('settings') : null),
    wake: () => { st.lastInput = Date.now(); if (st.screen === 'saver') go(st.me ? 'dash' : 'login'); },
    pane: (dir) => {
      if (st.screen === 'settings') return S.step?.(dir);
      const tabs = $$('[data-ptab]').filter((b) => getComputedStyle(b).display !== 'none');
      const i = tabs.findIndex((b) => b.getAttribute('aria-selected') === 'true');
      const next = tabs[(i + dir + tabs.length) % tabs.length];
      next?.click(); next?.focus();
    },
  });
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
