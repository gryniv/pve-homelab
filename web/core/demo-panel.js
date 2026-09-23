// Demo only: the DEMO ribbon opens a panel that adds systems and services to the made-up host,
// changes the weather and toggles the pending update. Loaded by app.js when /api/public says demo.

import { $, $$, esc, icon, t, toast } from './ui.js';
import { apply as applyI18n } from './i18n.js';
import { focusFirst } from './nav.js';

let app, hooks, state = null;

const OS_LABEL = { windows: 'Windows 11', ubuntu: 'Ubuntu', fedora: 'Fedora', debian: 'Debian', macos: 'macOS', linux: 'Linux' };
const WEATHER = ['', 'clear', 'partly', 'overcast', 'rain', 'thunder', 'snow', 'fog'];

async function call(path, body) {
  const r = await fetch(path, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body) });
  return r.json();
}

async function load() { state = await call('/api/demo/state'); }

const field = (label, control) => `<label class="fld">${esc(t(label))}${control}</label>`;

function render() {
  const s = state;
  $('#demoPanel').innerHTML = `
    <div class="dhead"><h3>${esc(t('demo.title'))}</h3><span class="mute">${esc(t('demo.lead'))}</span>
      <button class="chipbtn" type="button" id="demoClose">${icon('i-x')}${esc(t('set.close'))}</button></div>
    <div class="dgrid">
      <form class="dcard" id="dVm"><h4>${icon('i-monitor')}${esc(t('demo.add_system'))}</h4>
        ${field('demo.name', `<input id="dVmName" placeholder="my-desktop">`)}
        ${field('demo.os', `<select id="dVmOs">${s.os.map((o) => `<option value="${o}">${esc(OS_LABEL[o] || o)}</option>`).join('')}</select>`)}
        <div class="row2">${field('demo.cores', `<select id="dVmCores">${[2, 4, 8, 12, 16].map((n) => `<option ${n === 8 ? 'selected' : ''}>${n}</option>`).join('')}</select>`)}
          ${field('demo.ram', `<select id="dVmMem">${[4, 8, 16, 32, 64].map((n) => `<option value="${n}" ${n === 16 ? 'selected' : ''}>${n} GB</option>`).join('')}</select>`)}</div>
        <label class="check"><input type="checkbox" id="dVmGpu"> ${esc(t('demo.gpu'))}</label>
        <label class="check"><input type="checkbox" id="dVmRun"> ${esc(t('demo.running'))}</label>
        <button class="btn" type="submit">${icon('i-plus')}${esc(t('set.layout.add'))}</button></form>
      <form class="dcard" id="dSvc"><h4>${icon('i-grid')}${esc(t('demo.add_service'))}</h4>
        ${field('demo.app', `<select id="dSvcApp">${s.apps.map((a) => `<option value="${a}">${esc(a)}</option>`).join('')}</select>`)}
        ${field('demo.name', `<input id="dSvcName" placeholder="${esc(t('demo.name_auto'))}">`)}
        <div class="gl">${esc(t('demo.via'))}</div>
        <div class="seg" id="dSvcVia">${['caddy', 'port', 'notes'].map((v, i) => `<button type="button" data-v="${v}" aria-pressed="${i === 0}">${esc(t('demo.via_' + v))}</button>`).join('')}</div>
        <button class="btn" type="submit">${icon('i-plus')}${esc(t('set.layout.add'))}</button></form>
      <div class="dcard"><h4>${icon('i-cloud')}${esc(t('demo.world'))}</h4>
        <div class="gl">${esc(t('set.s.weather'))}</div>
        <div class="seg wrap" id="dWx">${WEATHER.map((k) => `<button type="button" data-v="${k}" aria-pressed="${k === s.weather}">${esc(k ? t('wx.' + k) : t('demo.real'))}</button>`).join('')}</div>
        <label class="check"><input type="checkbox" id="dUpd" ${s.update ? 'checked' : ''}> ${esc(t('demo.update'))}</label>
        <div class="gl">${esc(t('demo.added'))}</div>
        <div class="dlist">${s.added.length ? s.added.map((a) => `<div class="drow"><span>${a.type === 'qemu' ? 'VM' : 'CT'} ${a.id} · <b>${esc(a.name)}</b> <span class="mute">${esc(a.what)}</span></span>
          <button type="button" class="chipbtn" data-rm="${a.id}" title="${esc(t('set.layout.remove'))}">${icon('i-x')}</button></div>`).join('') : `<div class="mute">${esc(t('demo.nothing'))}</div>`}</div>
        <button class="btn ghost" type="button" id="dReset">${icon('i-refresh')}${esc(t('demo.reset'))}</button>
      </div>
    </div>`;
  bind();
}

async function changed(msg) {
  await load();
  render();
  await hooks.refresh();
  if (msg) toast(msg);
}

function bind() {
  $('#demoClose').onclick = close;
  let via = 'caddy';
  $$('#dSvcVia button').forEach((b) => (b.onclick = () => { via = b.dataset.v; $$('#dSvcVia button').forEach((x) => x.setAttribute('aria-pressed', x === b)); }));
  $('#dVm').onsubmit = async (e) => {
    e.preventDefault();
    await call('/api/demo/vm', { name: $('#dVmName').value, os: $('#dVmOs').value, cores: +$('#dVmCores').value,
      mem: +$('#dVmMem').value, gpu: $('#dVmGpu').checked, running: $('#dVmRun').checked });
    changed(t('demo.added_system'));
  };
  $('#dSvc').onsubmit = async (e) => {
    e.preventDefault();
    await call('/api/demo/service', { icon: $('#dSvcApp').value, name: $('#dSvcName').value, via });
    changed(t('demo.added_service'));
  };
  $$('#dWx button').forEach((b) => (b.onclick = async () => {
    await call('/api/demo/world', { weather: b.dataset.v });
    await changed();
    hooks.weather();
  }));
  $('#dUpd').onchange = async (e) => { await call('/api/demo/world', { update: e.target.checked }); changed(); };
  $$('[data-rm]', $('#demoPanel')).forEach((b) => (b.onclick = async () => { await call('/api/demo/remove', { id: +b.dataset.rm }); changed(); }));
  $('#dReset').onclick = async () => { await call('/api/demo/reset', {}); await changed(t('demo.reset_done')); hooks.weather(); };
}

async function open() {
  await load();
  render();
  $('#demoLayer').hidden = false;
  focusFirst($('#demoLayer'));
}

function close() {
  $('#demoLayer').hidden = true;
  $('#demoRibbon').focus();
}

export function initDemo(a, h) {
  app = a; hooks = h;
  const ribbon = $('#demoRibbon');
  ribbon.hidden = false;
  applyI18n(ribbon);
  ribbon.onclick = open;
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#demoLayer').hidden) { e.stopImmediatePropagation(); close(); }
  }, true);
  setTimeout(() => toast(t('demo.hint')), 2500);
}
