// Per-user settings panel. Every change is applied live and saved to the user's file.

import * as W from './widgets.js';
import { current as currentLang } from './i18n.js';
import { $, $$, icon, esc, AVATARS, toast, keepFocus, t } from './ui.js';

const ZONES = {
  login: { title: 'set.layout.zone_login', sub: 'set.layout.zone_login_sub' },
  side: { title: 'set.layout.zone_side', sub: 'set.layout.zone_side_sub' },
};

const SECTIONS = [
  ['look', 'i-palette'], ['layout', 'i-layout'], ['saver', 'i-moon'], ['weather', 'i-cloud'],
  ['launch', 'i-gpu'], ['services', 'i-grid'], ['account', 'i-user'],
];

let app, current = 'look', saveTimer;

const sw = (id, on) => `<span class="sw"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><i></i></span>`;
const tgl = (id, on, title, sub = '') => `<label class="tgl"><span>${esc(t(title))}${sub ? `<small>${esc(t(sub))}</small>` : ''}</span>${sw(id, on)}</label>`;
const seg = (id, val, opts) => `<div class="seg" id="${id}">${opts.map(([v, label]) => `<button type="button" data-v="${v}" aria-pressed="${v === val}">${esc(label)}</button>`).join('')}</div>`;
const lead = (key, vars) => `<p class="lead">${esc(t(key, vars))}</p>`;
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

const views = {
  look(p) {
    const lang = currentLang();
    return `<h3>${t('set.s.look')}</h3>${lead('set.look.lead')}
      <div class="grp"><div class="gl">${t('set.look.language')}</div>
        ${seg('langSeg', lang, app.pub().languages.map((l) => [l.code, l.name]))}</div>
      <div class="grp"><div class="gl">${t('set.look.theme')}</div><div class="skins">${app.pub().themes.map((th) => `
        <button type="button" class="skin${p.skin === th.id ? ' sel' : ''}" data-skin="${th.id}">
          <div class="pv" style="background:${esc(th.preview)}"><i style="background:${esc(th.accent)}"></i></div>
          <span>${esc(pick(th.name, lang))}<small>${esc(pick(th.desc, lang))}</small></span></button>`).join('')}</div></div>
      <div class="grp"><div class="gl">${t('set.look.background')}</div>${seg('bgSeg', p.background, [['scene', t('set.look.bg_scene')], ['still', t('set.look.bg_still')], ['solid', t('set.look.bg_solid')]])}</div>
      <div class="grp"><div class="gl">${t('set.look.behaviour')}</div>
        ${tgl('pWx', p.weather_react, 'set.look.wx', 'set.look.wx_sub')}
        ${tgl('pSky', p.sky_by_time, 'set.look.sky', 'set.look.sky_sub')}</div>`;
  },
  layout(p) {
    const zone = (z) => {
      const ids = p.layout[z] || [];
      const reg = W.all();
      const avail = W.allowed(z).filter((w) => !ids.includes(w.id));
      return `<div class="zbox"><div class="zt">${icon(z === 'login' ? 'i-lock' : 'i-layout')}${t(ZONES[z].title)}</div><div class="zs">${t(ZONES[z].sub)}</div>
        ${ids.map((id, i) => `<div class="wrow"><span class="grip">⋮⋮</span><span class="nm">${esc(reg[id]?.title || id)}</span>
          <button type="button" data-mv="${z}|${i}|-1" ${i === 0 ? 'disabled' : ''} title="${t('set.layout.up')}">${icon('i-up')}</button>
          <button type="button" data-mv="${z}|${i}|1" ${i === ids.length - 1 ? 'disabled' : ''} title="${t('set.layout.down')}">${icon('i-down')}</button>
          <button type="button" data-rm="${z}|${i}" title="${t('set.layout.remove')}">${icon('i-x')}</button></div>`).join('') || `<div class="mute" style="font-size:.85em;padding:.4em 0">${t('set.layout.empty')}</div>`}
        <div class="addw"><select id="add-${z}" aria-label="${esc(t(ZONES[z].title))}">${avail.length ? avail.map((w) => `<option value="${w.id}">${esc(w.title)}</option>`).join('') : `<option value="">${t('set.layout.all_added')}</option>`}</select>
        <button class="btn" type="button" data-add="${z}" ${avail.length ? '' : 'disabled'}>${icon('i-plus')}${t('set.layout.add')}</button></div></div>`;
    };
    return `<h3>${t('set.s.layout')}</h3>${lead('set.layout.lead')}
      <div class="zones">${zone('login')}${zone('side')}</div>
      <div class="grp" style="margin-top:1.4em"><div class="gl">${t('set.layout.note')}</div>
      <div class="fld" style="max-width:40em"><textarea id="pNote" rows="4">${esc(p.note)}</textarea></div></div>`;
  },
  saver(p) {
    return `<h3>${t('set.s.saver')}</h3>${lead('set.saver.lead', { n: app.pub().saver_after_min })}
      ${tgl('pFx', p.saver.fx, 'set.saver.fx', 'set.saver.fx_sub')}
      ${tgl('pClock', p.saver.clock, 'set.saver.clock')}
      <div style="margin-top:1em"><button class="btn" type="button" id="showSaver">${icon('i-moon')}${t('set.saver.show')}</button></div>`;
  },
  weather(p) {
    const cfg = app.pub().weather;
    return `<h3>${t('set.s.weather')}</h3>${lead('set.weather.lead', { city: cfg.city })}
      <form id="wxForm"><div class="fld">${t('set.weather.city')}<input id="wxCity" value="${esc(p.weather.city)}" placeholder="${esc(cfg.city)}"></div>
      <div class="fld">${t('set.weather.units')}<select id="wxUnits"><option value="">${t('set.weather.units_default')}</option><option value="c" ${p.weather.units === 'c' ? 'selected' : ''}>°C, m/s</option><option value="f" ${p.weather.units === 'f' ? 'selected' : ''}>°F, mph</option></select></div>
      <button class="btn" type="submit">${t('set.weather.save')}</button></form>`;
  },
  launch(p) {
    return `<h3>${t('set.s.launch')}</h3>${lead('set.launch.lead')}
      <div class="grp"><div class="gl">${t('set.launch.gpu')}</div>${seg('gpuSeg', p.launch.gpu, [['auto', t('set.launch.gpu_auto')], ['igpu', t('set.launch.gpu_igpu')]])}</div>
      ${tgl('pAsk', p.launch.ask, 'set.launch.ask', 'set.launch.ask_sub')}`;
  },
  services(p) {
    const list = app.services();
    return `<h3>${t('set.s.services')}</h3>${lead('set.services.lead')}
      <div class="svclist">${list.map((s) => `<label><img src="/icons/${esc(s.icon || s.key)}.svg" alt="" onerror="this.style.visibility='hidden'">${esc(s.name)}
        <input type="checkbox" data-hide="${esc(s.key)}" ${p.hidden_services.includes(s.key) ? '' : 'checked'}></label>`).join('')}</div>`;
  },
  account(p) {
    return `<h3>${t('set.s.account')}</h3>${lead('set.account.lead')}
      <div class="grp"><div class="gl">${t('set.account.avatar')}</div><div class="avpick">${AVATARS.map((a, i) => `<button type="button" style="background:${a}" aria-pressed="${p.avatar === i}" data-av="${i}" title="${esc(t('set.account.color', { n: i + 1 }))}"></button>`).join('')}</div></div>
      ${tgl('pShow', p.show_on_login, 'set.account.show', 'set.account.show_sub')}`;
  },
};

function bind(p) {
  $$('[data-skin]', $('#settingsBox')).forEach((b) => (b.onclick = () => save({ skin: b.dataset.skin })));
  const segBind = (id, fn) => $$(`#${id} button`).forEach((b) => (b.onclick = () => { fn(b.dataset.v); render(); }));
  segBind('langSeg', (v) => { save({ lang: v }); app.useLang(v); });
  segBind('bgSeg', (v) => save({ background: v }));
  segBind('gpuSeg', (v) => save({ launch: { ...p.launch, gpu: v } }));
  const chk = (id, fn) => { const el = $('#' + id); if (el) el.onchange = () => fn(el.checked); };
  chk('pWx', (v) => save({ weather_react: v }));
  chk('pSky', (v) => save({ sky_by_time: v }));
  chk('pFx', (v) => save({ saver: { ...p.saver, fx: v } }));
  chk('pClock', (v) => save({ saver: { ...p.saver, clock: v } }));
  chk('pAsk', (v) => save({ launch: { ...p.launch, ask: v } }));
  chk('pShow', (v) => save({ show_on_login: v }));
  $('#showSaver') && ($('#showSaver').onclick = () => app.go('saver'));
  $('#pNote') && ($('#pNote').onchange = (e) => save({ note: e.target.value }, { relayout: true }));
  $('#wxForm') && ($('#wxForm').onsubmit = async (e) => {
    e.preventDefault();
    save({ weather: { city: $('#wxCity').value.trim(), units: $('#wxUnits').value } });
    try { await app.weather(true); toast(t('set.weather.updated')); app.applyPrefs({ relayout: true }); } catch (err) { toast(err.message, true); }
  });
  $$('[data-av]').forEach((b) => (b.onclick = () => { save({ avatar: +b.dataset.av }); render(); }));
  $$('[data-hide]').forEach((c) => (c.onchange = () => {
    const k = c.dataset.hide;
    save({ hidden_services: c.checked ? p.hidden_services.filter((x) => x !== k) : [...p.hidden_services, k] });
  }));
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
  const p = app.prefs();
  const me = app.me();
  const av = app.avatarOf(me);
  $('#settingsBox').innerHTML = `
    <nav class="snav">
      <div class="me2"><span class="av" style="background:${av.bg}">${av.inner}</span><div><b>${esc(me.name)}</b><small>${esc(me.id)}</small></div></div>
      ${SECTIONS.map(([id, ic]) => `<button type="button" data-sp="${id}" aria-selected="${id === current}">${icon(ic)}${t('set.s.' + id)}</button>`).join('')}
      <span class="sp"></span><span class="saved" id="savedNote">${t('set.saved_hint')}</span>
    </nav>
    <div class="scont"><button class="chipbtn sclose" type="button" id="sClose">${icon('i-x')}${t('set.close')}</button>${views[current](p)}</div>`;
  $$('[data-sp]').forEach((b) => (b.onclick = () => { current = b.dataset.sp; render(); }));
  $('#sClose').onclick = () => app.go('dash');
  bind(p);
}

export function open(section) {
  if (section) current = section;
  render();
}

export function init(a) { app = a; }
