// Per-user settings panel. Every change is applied live and saved to the user's file.
// Sign-in screen settings for the whole host live in the "login" section (admins only).

import * as W from './widgets.js';
import * as BG from './backgrounds.js';
import * as F from './fonts.js';
import { arrange, moved } from './order.js';
import { current as currentLang } from './i18n.js';
import { $, $$, icon, esc, AVATARS, toast, confirmBox, keepFocus, t } from './ui.js';

const ZONES = {
  login: { title: 'set.layout.zone_login', sub: 'set.layout.zone_login_sub' },
  side: { title: 'set.layout.zone_side', sub: 'set.layout.zone_side_sub' },
};

const SECTIONS = [
  ['look', 'i-palette'], ['login', 'i-lock'], ['dash', 'i-layout'], ['systems', 'i-monitor'],
  ['weather', 'i-cloud'], ['about', 'i-info'],
];
const LOOK_TABS = [['theme', 'set.look.tab_theme'], ['bg', 'set.look.tab_bg'], ['fonts', 'set.look.tab_fonts'], ['clock', 'set.look.tab_clock']];

let app, current = 'look', lookTab = 'theme', saveTimer, loginCfg = null, loginTimer, openW = '', stopPreview = null, logs = null;

const sw = (id, on) => `<span class="sw"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><i></i></span>`;
const tgl = (id, on, title, sub = '') => `<label class="tgl"><span>${esc(t(title))}${sub ? `<small>${esc(t(sub))}</small>` : ''}</span>${sw(id, on)}</label>`;
const seg = (id, val, opts) => `<div class="seg" id="${id}">${opts.map(([v, label]) => `<button type="button" data-v="${v}" aria-pressed="${v === val}">${esc(label)}</button>`).join('')}</div>`;
const lead = (key, vars) => `<p class="lead">${esc(t(key, vars))}</p>`;
const grp = (title, body) => `<div class="grp"><div class="gl">${esc(t(title))}</div>${body}</div>`;
const pick = (item, lang) => (item && typeof item === 'object' ? item[lang] || item.en || Object.values(item)[0] : item) || '';

function save(changes, { relayout = false } = {}) {
  const p = app.prefs();
  Object.assign(p, changes);
  app.applyPrefs({ relayout });
  clearTimeout(saveTimer);
  $('#savedNote') && ($('#savedNote').textContent = t('set.saving'));
  saveTimer = setTimeout(async () => {
    try {
      await app.api.put('/api/prefs', p);
      $('#savedNote') && ($('#savedNote').textContent = t('set.saved'));
    } catch (e) { toast(e.message, true); }
  }, 400);
}

function saveLogin(changes) {
  Object.assign(loginCfg.settings, changes);
  app.setLoginSettings(loginCfg.settings);
  clearTimeout(loginTimer);
  loginTimer = setTimeout(async () => {
    try { app.setLoginSettings(await app.api.put('/api/login-settings', loginCfg.settings)); $('#savedNote').textContent = t('set.saved'); }
    catch (e) { toast(e.message, true); }
  }, 400);
}

// Sort mode + a reorderable list with visibility switches (web services, systems).
function orderEditor(kind, list, p, hidden, label) {
  const mode = p.sort?.[kind] || 'manual';
  const rows = arrange(kind, list, p);
  const key = (x) => (kind === 'systems' ? String(x.vmid) : x.key);
  return `<div class="grp"><div class="gl">${t('set.sort')}</div>
      ${seg(`sort-${kind}`, mode, [['manual', t('set.sort_manual')], ['name', t('set.sort_name')], ['status', t('set.sort_status')]])}
      <p class="lead" style="margin:.7em 0 0">${esc(t('set.order_hint'))}</p></div>
    <div class="olist">${rows.map((x, i) => `<div class="orow">${label(x)}
      <button type="button" data-omv="${kind}|${esc(key(x))}|-1" ${i === 0 || mode !== 'manual' ? 'disabled' : ''} title="${t('set.layout.up')}">${icon('i-up')}</button>
      <button type="button" data-omv="${kind}|${esc(key(x))}|1" ${i === rows.length - 1 || mode !== 'manual' ? 'disabled' : ''} title="${t('set.layout.down')}">${icon('i-down')}</button>
      <span class="sw" title="${esc(t('set.visible'))}"><input type="checkbox" data-vis="${kind}|${esc(key(x))}" ${hidden.includes(key(x)) ? '' : 'checked'} aria-label="${esc(t('set.visible'))}"><i></i></span>
    </div>`).join('')}</div>`;
}

// One option of a widget as a form field (types are described in core/widgets.js).
function optField(w, o, val) {
  const id = `${w.id}|${o.key}`;
  const lbl = esc(w.t(o.label));
  const hint = o.hint ? `<small>${esc(w.t(o.hint))}</small>` : '';
  const ph = o.placeholder ? ` placeholder="${esc(w.t(o.placeholder))}"` : '';
  const choices = typeof o.choices === 'function' ? o.choices(app, currentLang()) : o.choices || [];
  switch (o.type) {
    case 'toggle':
      return `<label class="tgl"><span>${lbl}${hint}</span><span class="sw"><input type="checkbox" data-wo="${esc(id)}" ${val ? 'checked' : ''}><i></i></span></label>`;
    case 'select':
      return `<div class="fld">${lbl}<select data-wo="${esc(id)}">${choices.map(([v, k]) => `<option value="${esc(v)}" ${String(val) === String(v) ? 'selected' : ''}>${esc(w.t(k))}</option>`).join('')}</select>${hint}</div>`;
    case 'checks':
      return `<div class="fld">${lbl}<div class="checks">${choices.map(([v, k]) => `<label><input type="checkbox" data-wochk="${esc(id)}|${esc(v)}" ${(val || []).includes(v) ? 'checked' : ''}> ${esc(w.t(k))}</label>`).join('')}</div>${hint}</div>`;
    case 'number':
      return `<div class="fld">${lbl}<input type="number" data-wo="${esc(id)}" value="${esc(val)}" ${o.min != null ? `min="${o.min}"` : ''} ${o.max != null ? `max="${o.max}"` : ''}>${hint}</div>`;
    case 'list': case 'textarea':
      return `<div class="fld">${lbl}<textarea rows="4" data-wo="${esc(id)}"${ph}>${esc(val ?? '')}</textarea>${hint}</div>`;
    default:
      return `<div class="fld">${lbl}<input type="${o.type === 'date' ? 'date' : 'text'}" data-wo="${esc(id)}" value="${esc(val ?? '')}"${ph}>${hint}</div>`;
  }
}

// The options form of one widget in a zone, next to a live preview of it.
function widgetPanel(p, z, id) {
  const w = W.all()[id];
  const stored = p.widget_opts?.[id] || {};
  const form = w.options.length
    ? w.options.map((o) => optField(w, o, stored[o.key] ?? o.default)).join('')
    : `<p class="mute" style="font-size:.85em">${t('set.w.none')}</p>`;
  return `<div class="wcfg"><div class="wform">${form}</div>
    <div class="wprevbox"><div class="gl">${t('set.w.preview')}</div><div class="wprev" data-wprev="${z}|${id}"></div></div></div>`;
}

// A widget zone editor (login screen, dashboard side column).
function zone(p, z) {
  const ids = p.layout[z] || [];
  const reg = W.all();
  const avail = W.allowed(z).filter((w) => !ids.includes(w.id));
  return `<div class="zbox"><div class="zt">${icon(z === 'login' ? 'i-lock' : 'i-layout')}${t(ZONES[z].title)}</div><div class="zs">${t(ZONES[z].sub)}</div>
    ${ids.map((id, i) => `<div class="wrow${openW === `${z}|${id}` ? ' open' : ''}"><span class="grip">⋮⋮</span><span class="nm">${esc(reg[id]?.title || id)}</span>
      <button type="button" class="wgear" data-wcfg="${z}|${id}" aria-expanded="${openW === `${z}|${id}`}" title="${t('set.w.configure')}">${icon('i-gear')}</button>
      <button type="button" data-mv="${z}|${i}|-1" ${i === 0 ? 'disabled' : ''} title="${t('set.layout.up')}">${icon('i-up')}</button>
      <button type="button" data-mv="${z}|${i}|1" ${i === ids.length - 1 ? 'disabled' : ''} title="${t('set.layout.down')}">${icon('i-down')}</button>
      <button type="button" data-rm="${z}|${i}" title="${t('set.layout.remove')}">${icon('i-x')}</button></div>
      ${openW === `${z}|${id}` && reg[id] ? widgetPanel(p, z, id) : ''}`).join('') || `<div class="mute" style="font-size:.85em;padding:.4em 0">${t('set.layout.empty')}</div>`}
    <div class="addw"><select id="add-${z}" aria-label="${esc(t(ZONES[z].title))}">${avail.length ? avail.map((w) => `<option value="${w.id}">${esc(w.title)}</option>`).join('') : `<option value="">${t('set.layout.all_added')}</option>`}</select>
    <button class="btn" type="button" data-add="${z}" ${avail.length ? '' : 'disabled'}>${icon('i-plus')}${t('set.layout.add')}</button></div></div>`;
}

/* ---------------- look: tiles are mini monitors (backgrounds.js) ---------------- */
const lookOf = (p, over = {}) => ({ skin: p.skin || 'dusk', bg: p.background || 'scene', clock: p.clock || 'digital', fonts: p.fonts || {}, ...over });
const monitor = (look) => BG.mini(look, F.css(look.fonts));
const tile = (attr, sel, look, name, sub = '') => `
  <button type="button" class="skin${sel ? ' sel' : ''}" ${attr}>${monitor(look)}
    <span>${esc(name)}${sub ? `<small>${esc(sub)}</small>` : ''}</span></button>`;

const lookViews = {
  theme(p, lang) {
    return grp('set.look.theme', `<div class="skins looks">${app.pub().themes.map((th) =>
      tile(`data-skinpick="${th.id}"`, p.skin === th.id, lookOf(p, { skin: th.id }), pick(th.name, lang), pick(th.desc, lang))).join('')}</div>`);
  },
  bg(p, lang) {
    const group = (g, title) => grp(title, `<div class="skins looks">${BG.byGroup(g).map((b) =>
      tile(`data-bgk="${b.id}"`, (p.background || 'scene') === b.id, lookOf(p, { bg: b.id }), BG.nameOf(b, lang))).join('')}</div>`);
    return group('scape', 'set.look.bg_scapes') + group('flat', 'set.look.bg_simple');
  },
  fonts(p, lang) {
    const f = p.fonts || {};
    const list = (slot) => `<div class="fonts">
      <button type="button" class="ftile${!f[slot] ? ' sel' : ''}" data-font="${slot}|"><span class="fs">Aa Бб 12:34</span><span class="fn">${t('set.look.font_theme')}</span></button>
      ${F.all().map((m) => `<button type="button" class="ftile${f[slot] === m.id ? ' sel' : ''}" data-font="${slot}|${m.id}">
        <span class="fs" style="font-family:${esc(m.family)}">Aa Бб 12:34</span><span class="fn">${esc(pick(m.name, lang))}</span></button>`).join('')}</div>`;
    return `<div class="lookres">${monitor(lookOf(p))}<p class="lead">${esc(t('set.look.result'))}</p></div>`
      + grp('set.look.font_display', list('display')) + grp('set.look.font_ui', list('ui'));
  },
  clock(p, lang) {
    return grp('set.look.clock', `<div class="skins looks">${app.pub().clocks.map((c) =>
      tile(`data-clk="${c.id}"`, (p.clock || 'digital') === c.id, lookOf(p, { clock: c.id }), pick(c.name, lang), pick(c.desc, lang))).join('')}</div>`);
  },
};

// Error journal (Settings → About): backend warnings and the screens' own errors.
function journal() {
  if (!logs) {
    logs = { pending: true };
    app.api.get('/api/logs').then((r) => { logs = r; render(); })
      .catch((e) => { logs = { denied: e.status === 403 || e.status === 401, error: e.message }; render(); });
  }
  if (logs.pending) return grp('log.title', '<p class="mute">…</p>');
  if (logs.denied) return '';
  if (logs.error) return grp('log.title', `<p class="bad">${esc(logs.error)}</p>`);
  const fmt = new Intl.DateTimeFormat(currentLang(), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const src = (x) => (x.startsWith('client') ? t('log.src_client', { kind: x.split(':')[1] || '' }) : t('log.src_server'));
  const rows = logs.entries.map((e) => `<details class="lrow ${e.level}">
      <summary><span class="lt">${esc(fmt.format(new Date(e.last * 1000)))}</span><span class="ls">${esc(src(e.source))}</span>
        <span class="lm">${esc(e.msg)}</span>${e.count > 1 ? `<span class="lc">×${e.count}</span>` : ''}</summary>
      <div class="ld">${[e.seat && `${t('log.seat')}: ${esc(e.seat)}`, e.user && `${t('log.user')}: ${esc(e.user)}`, e.where && esc(e.where),
        e.count > 1 && t('log.first', { t: fmt.format(new Date(e.time * 1000)) })].filter(Boolean).join(' · ')}</div>
      ${e.detail ? `<pre>${esc(e.detail)}</pre>` : ''}</details>`).join('');
  return grp('log.title', `<p class="lead" style="margin-top:0">${esc(t('log.lead', { file: logs.file }))}</p>
    <div class="lbar"><button class="chipbtn" type="button" id="logRefresh">${icon('i-refresh')}${t('log.refresh')}</button>
      ${logs.can_clear && logs.entries.length ? `<button class="chipbtn" type="button" id="logClear">${icon('i-x')}${t('log.clear')}</button>` : ''}
      <span class="mute">${t('log.count', { n: logs.entries.length })}</span></div>
    <div class="llist">${rows || `<p class="ok" style="margin:.4em 0">${t('log.empty')}</p>`}</div>`);
}

const views = {
  look(p) {
    const lang = currentLang();
    if (lookTab === 'fonts') F.all().forEach((m) => F.load(m.id));
    return `<h3>${t('set.s.look')}</h3>${lead('set.look.lead')}
      <div class="lookbar">${seg('lookTabs', lookTab, LOOK_TABS.map(([id, k]) => [id, t(k)]))}
        <span class="sp"></span>${seg('langSeg', lang, app.pub().languages.map((l) => [l.code, l.name]))}</div>
      <p class="lead hint">${icon('i-monitor')}${esc(t('set.look.hover'))}</p>
      ${lookViews[lookTab](p, lang)}`;
  },
  login(p) {
    const L = loginCfg?.settings;
    const host = !loginCfg || loginCfg.pending ? `<p class="mute">…</p>` : !loginCfg.can_edit ? `<p class="lead">${esc(t('set.login.admin_only'))}</p>` : `
      <div class="fld" style="max-width:30em">${t('set.login.title')}<input id="lTitle" value="${esc(L.title)}" placeholder="${esc(t('set.login.title_ph'))}" maxlength="80"></div>
      <div class="grp"><div class="gl">${t('set.login.avatars')}</div>${seg('lAv', L.avatars, [['large', t('set.login.av_large')], ['small', t('set.login.av_small')]])}</div>
      ${tgl('lRemember', L.remember_last, 'set.login.remember', 'set.login.remember_sub')}
      ${tgl('lOther', L.other_user, 'set.login.other', 'set.login.other_sub')}
      ${tgl('lDate', L.date, 'set.login.date')}
      ${tgl('lHost', L.hostline, 'set.login.hostline')}`;
    return `<h3>${t('set.s.login')}</h3>${lead('set.login.lead')}
      ${grp('set.login.me', `${tgl('pShow', p.show_on_login, 'set.account.show', 'set.account.show_sub')}
        <div class="gl" style="margin-top:1em">${t('set.account.avatar')}</div>
        <div class="avpick">${AVATARS.map((a, i) => `<button type="button" style="background:${a}" aria-pressed="${p.avatar === i}" data-av="${i}" title="${esc(t('set.account.color', { n: i + 1 }))}"></button>`).join('')}</div>`)}
      <div class="zones one">${zone(p, 'login')}</div>
      ${grp('set.login.host', host)}`;
  },
  dash(p) {
    return `<h3>${t('set.s.dash')}</h3>${lead('set.dash.lead')}
      <div class="zones one">${zone(p, 'side')}</div>
      <h4 class="subh">${t('set.dash.services')}</h4>${lead('set.services.lead')}
      ${orderEditor('services', app.services(), p, p.hidden_services,
        (x) => `<img src="/icons/${esc(x.icon || x.key)}.svg" alt="" onerror="this.style.visibility='hidden'"><span class="nm">${esc(x.name)}<small>${esc(x.host)}</small></span>`)}`;
  },
  systems(p) {
    return `<h3>${t('set.s.systems')}</h3>${lead('set.systems.lead', { tag: '«' + (app.pub().systems_tag || 'seat') + '»' })}
      ${grp('set.systems.launch', `${seg('gpuSeg', p.launch.gpu, [['auto', t('set.launch.gpu_auto')], ['igpu', t('set.launch.gpu_igpu')]])}
        <p class="lead" style="margin:.6em 0 0">${esc(t('set.launch.lead'))}</p>${tgl('pAsk', p.launch.ask, 'set.launch.ask', 'set.launch.ask_sub')}`)}
      ${orderEditor('systems', app.systems(), p, (p.hidden_systems || []).map(String),
        (x) => `<span class="nm">${esc(x.name)}<small>VM ${x.vmid} · ${esc(t(x.status === 'running' ? 'guest.running' : 'guest.stopped'))}</small></span>`)}`;
  },
  weather(p) {
    const cfg = app.pub().weather;
    return `<h3>${t('set.s.weather')}</h3>${lead('set.weather.lead', { city: cfg.city })}
      <form id="wxForm" class="wxform"><div class="fld">${t('set.weather.city')}<input id="wxCity" value="${esc(p.weather.city)}" placeholder="${esc(cfg.city)}"></div>
      <div class="fld">${t('set.weather.units')}<select id="wxUnits"><option value="">${t('set.weather.units_default')}</option><option value="c" ${p.weather.units === 'c' ? 'selected' : ''}>°C, m/s</option><option value="f" ${p.weather.units === 'f' ? 'selected' : ''}>°F, mph</option></select></div>
      <button class="btn" type="submit">${t('set.weather.save')}</button></form>
      ${grp('set.weather.behaviour', `${tgl('pWx', p.weather_react, 'set.look.wx', 'set.look.wx_sub')}${tgl('pSky', p.sky_by_time, 'set.look.sky', 'set.look.sky_sub')}`)}
      ${grp('set.weather.saver', `<p class="lead" style="margin-top:0">${esc(t('set.saver.lead', { n: app.pub().saver_after_min }))}</p>
        ${tgl('pFx', p.saver.fx, 'set.saver.fx', 'set.saver.fx_sub')}${tgl('pClock', p.saver.clock, 'set.saver.clock')}
        <div style="margin-top:1em"><button class="btn" type="button" id="showSaver">${icon('i-moon')}${t('set.saver.show')}</button></div>`)}`;
  },
  about() {
    const a = app.about(), pub = app.pub(), u = app.updateStatus();
    const row = (k, v) => `<div class="kv"><span class="mute">${esc(t(k))}</span><b>${v}</b></div>`;
    const repo = a.repo || (pub.app.repo ? `https://github.com/${pub.app.repo}` : '');
    return `<h3>${esc(a.name || 'PVE Seat')}</h3>${lead('about.lead')}
      <div class="grp about-box">
        ${row('about.version', `v${esc(pub.app.version)}${u?.available ? ` · <span class="acc-text">${esc(t('about.update_new', { v: u.latest.version ? 'v' + u.latest.version : (u.latest.commit || '').slice(0, 7) }))}</span>` : u?.enabled ? ` · ${esc(t('about.update_ok'))}` : ''}`)}
        ${a.author ? row('about.author', a.author_url ? `<a href="${esc(a.author_url)}" target="_blank" rel="noopener">${esc(a.author)}</a>` : esc(a.author)) : ''}
        ${row('about.repo', repo ? `<a href="${esc(repo)}" target="_blank" rel="noopener">${esc(repo.replace(/^https?:\/\//, ''))}</a>` : esc(t('about.none')))}
        ${row('about.license', esc(a.license || t('about.none')))}
        ${row('about.host', `Proxmox VE ${esc(pub.version)} · ${esc(pub.node)}`)}
      </div>
      <div class="grp"><div class="gl">${t('about.credits')}</div>
        <div class="mute credits">noVNC (MPL-2.0) · Meteocons, Bas Milius (MIT) · dashboard-icons, homarr-labs · Open-Meteo · Google Fonts (OFL) · cage · Chromium</div></div>
      <button class="btn ghost" type="button" id="showHelp">${icon('i-info')}${t('help.title')}</button>
      <div style="margin-top:1.6em">${journal()}</div>`;
  },
};

function bind(p) {
  const box = $('#settingsBox');
  const segBind = (id, fn) => $$(`#${id} button`).forEach((b) => (b.onclick = () => { fn(b.dataset.v); render(); }));
  const chk = (id, fn) => { const el = $('#' + id); if (el) el.onchange = () => fn(el.checked); };
  // look
  segBind('lookTabs', (v) => { lookTab = v; });
  segBind('langSeg', (v) => { save({ lang: v }); app.useLang(v); });
  $$('[data-skinpick]', box).forEach((b) => (b.onclick = () => { save({ skin: b.dataset.skinpick }); render(); }));
  $$('[data-bgk]', box).forEach((b) => (b.onclick = () => { save({ background: b.dataset.bgk }); render(); }));
  $$('[data-clk]', box).forEach((b) => (b.onclick = () => { save({ clock: b.dataset.clk }); render(); }));
  $$('[data-font]', box).forEach((b) => (b.onclick = () => {
    const [slot, id] = b.dataset.font.split('|');
    save({ fonts: { ...(p.fonts || {}), [slot]: id } }); render();
  }));
  BG.hydrate(box, app.locale());
  // login
  chk('pShow', (v) => save({ show_on_login: v }));
  $$('[data-av]').forEach((b) => (b.onclick = () => { save({ avatar: +b.dataset.av }); render(); }));
  segBind('lAv', (v) => saveLogin({ avatars: v }));
  chk('lRemember', (v) => saveLogin({ remember_last: v }));
  chk('lOther', (v) => saveLogin({ other_user: v }));
  chk('lDate', (v) => saveLogin({ date: v }));
  chk('lHost', (v) => saveLogin({ hostline: v }));
  $('#lTitle') && ($('#lTitle').oninput = (e) => saveLogin({ title: e.target.value.trim() }));
  // dash / systems
  segBind('gpuSeg', (v) => save({ launch: { ...p.launch, gpu: v } }));
  chk('pAsk', (v) => save({ launch: { ...p.launch, ask: v } }));
  for (const kind of ['services', 'systems']) segBind(`sort-${kind}`, (v) => save({ sort: { ...(p.sort || {}), [kind]: v } }));
  $$('[data-omv]').forEach((b) => (b.onclick = async () => {
    const [kind, key, d] = b.dataset.omv.split('|');
    const list = kind === 'systems' ? app.systems() : app.services();
    await app.saveOrder(kind, moved(kind, list, p, key, { delta: +d }));
    render();
  }));
  $$('[data-vis]').forEach((c) => (c.onchange = () => {
    const [kind, key] = c.dataset.vis.split('|');
    const field = kind === 'systems' ? 'hidden_systems' : 'hidden_services';
    const cur = (p[field] || []).map(String);
    save({ [field]: c.checked ? cur.filter((x) => x !== key) : [...cur, key] });
  }));
  // weather & saver
  chk('pWx', (v) => save({ weather_react: v }));
  chk('pSky', (v) => save({ sky_by_time: v }));
  chk('pFx', (v) => save({ saver: { ...p.saver, fx: v } }));
  chk('pClock', (v) => save({ saver: { ...p.saver, clock: v } }));
  $('#showSaver') && ($('#showSaver').onclick = () => app.go('saver'));
  $('#wxForm') && ($('#wxForm').onsubmit = async (e) => {
    e.preventDefault();
    save({ weather: { city: $('#wxCity').value.trim(), units: $('#wxUnits').value } });
    try { await app.weather(true); toast(t('set.weather.updated')); app.applyPrefs({ relayout: true }); } catch (err) { toast(err.message, true); }
  });
  $('#showHelp') && ($('#showHelp').onclick = () => app.showHelp());
  $('#logRefresh') && ($('#logRefresh').onclick = () => { logs = null; render(); });
  $('#logClear') && ($('#logClear').onclick = async () => {
    if (!(await confirmBox(t('log.clear_q'), t('log.clear_text'), t('log.clear')))) return;
    try { await app.api.del('/api/logs'); logs = null; render(); } catch (e) { toast(e.message, true); }
  });
  // widget zones
  $$('[data-wcfg]', box).forEach((b) => (b.onclick = () => { openW = openW === b.dataset.wcfg ? '' : b.dataset.wcfg; render(); }));
  const setOpt = (id, key, v) => {
    const all = { ...(p.widget_opts || {}) };
    all[id] = { ...(all[id] || {}), [key]: v };
    save({ widget_opts: all }, { relayout: true });
    preview();
  };
  $$('[data-wo]', box).forEach((el) => (el.onchange = () => {
    const [id, key] = el.dataset.wo.split('|');
    setOpt(id, key, el.type === 'checkbox' ? el.checked : el.type === 'number' ? +el.value : el.value);
  }));
  $$('[data-wochk]', box).forEach((el) => (el.onchange = () => {
    const [id, key] = el.dataset.wochk.split('|');
    setOpt(id, key, $$(`[data-wochk^="${id}|${key}|"]`, box).filter((c) => c.checked).map((c) => c.dataset.wochk.split('|')[2]));
  }));
  const preview = () => {
    stopPreview?.();
    stopPreview = null;
    const el = $('[data-wprev]', box);
    if (!el) return;
    const [z, id] = el.dataset.wprev.split('|');
    const inner = document.createElement('div');
    el.replaceChildren(inner);
    stopPreview = W.mount(inner, id, z, { app, opts: p.widget_opts });
  };
  preview();
  const lay = () => JSON.parse(JSON.stringify(p.layout));
  $$('[data-mv]').forEach((b) => (b.onclick = () => {
    const [z, i, d] = b.dataset.mv.split('|'); const L = lay(); const a = L[z]; const j = +i + +d;
    [a[i], a[j]] = [a[j], a[i]]; save({ layout: L }, { relayout: true }); render();
  }));
  $$('[data-rm]').forEach((b) => (b.onclick = () => {
    const [z, i] = b.dataset.rm.split('|'); const L = lay(); L[z].splice(+i, 1); save({ layout: L }, { relayout: true }); render();
  }));
  $$('[data-add]').forEach((b) => (b.onclick = () => {
    const z = b.dataset.add, v = $('#add-' + z).value;
    if (v) { const L = lay(); (L[z] ||= []).push(v); save({ layout: L }, { relayout: true }); render(); }
  }));
}

export function render() {
  keepFocus($('#settingsBox'), draw);
}

function draw() {
  stopPreview?.();
  stopPreview = null;
  const p = app.prefs();
  const me = app.me();
  const av = app.avatarOf(me);
  if (!SECTIONS.some(([id]) => id === current)) current = 'look';
  if (loginCfg && loginCfg.for !== me.id) loginCfg = null;
  if (current === 'login' && !loginCfg) {
    loginCfg = { for: me.id, pending: true };
    app.api.get('/api/login-settings').then((r) => { loginCfg = { ...r, for: me.id }; render(); }).catch((e) => { loginCfg = null; toast(e.message, true); });
  }
  $('#settingsBox').innerHTML = `
    <nav class="snav">
      <div class="me2"><span class="av" style="background:${av.bg}">${av.inner}</span><div><b>${esc(me.name)}</b><small>${esc(me.id)}</small></div></div>
      ${SECTIONS.map(([id, ic]) => `<button type="button" data-sp="${id}" aria-selected="${id === current}">${icon(ic)}${t('set.s.' + id)}</button>`).join('')}
      <span class="sp"></span><span class="saved" id="savedNote">${t('set.saved_hint')}</span>
    </nav>
    <div class="scont"><button class="chipbtn sclose" type="button" id="sClose">${icon('i-x')}${t('set.close')}</button>${views[current](p)}</div>`;
  $$('[data-sp]').forEach((b) => (b.onclick = () => { current = b.dataset.sp; if (current === 'about') logs = null; render(); }));
  $('#sClose').onclick = () => app.go('dash');
  bind(p);
}

export function open(section) {
  if (section) current = section;
  render();
}

export function init(a) { app = a; }
