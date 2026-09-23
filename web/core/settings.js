// Per-user settings panel. Every change is applied live and saved to the user's file.

import * as W from './widgets.js';
import { $, $$, icon, esc, AVATARS, toast, keepFocus } from './ui.js';

const ZONES = {
  login: { title: 'Екран входу', sub: 'під годинником, по 2 в ряд; тільки публічні віджети' },
  side: { title: 'Ліва колонка панелі', sub: 'зверху вниз' },
};

const SECTIONS = [
  ['look', 'i-palette', 'Вигляд'],
  ['layout', 'i-layout', 'Макет і віджети'],
  ['saver', 'i-moon', 'Заставка'],
  ['weather', 'i-cloud', 'Погода'],
  ['launch', 'i-gpu', 'Запуск систем'],
  ['services', 'i-grid', 'Вебсервіси'],
  ['account', 'i-user', 'Обліковий запис'],
];

let app, current = 'look', saveTimer;

const sw = (id, on) => `<span class="sw"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><i></i></span>`;
const tgl = (id, on, title, sub = '') => `<label class="tgl"><span>${title}${sub ? `<small>${sub}</small>` : ''}</span>${sw(id, on)}</label>`;
const seg = (id, val, opts) => `<div class="seg" id="${id}">${opts.map(([v, t]) => `<button type="button" data-v="${v}" aria-pressed="${v === val}">${t}</button>`).join('')}</div>`;

function save(changes, { relayout = false } = {}) {
  const p = app.prefs();
  Object.assign(p, changes);
  app.applyPrefs({ relayout });
  clearTimeout(saveTimer);
  $('#savedNote') && ($('#savedNote').textContent = 'зберігаю…');
  saveTimer = setTimeout(async () => {
    try {
      await app.api.put('/api/prefs', p);
      $('#savedNote') && ($('#savedNote').textContent = 'збережено');
    } catch (e) { toast(e.message, true); }
  }, 400);
}

const views = {
  look(p) {
    return `<h3>Вигляд</h3><p class="lead">Тема змінює кольори, шрифти й настрій пейзажу. Налаштування діють тільки для тебе.</p>
      <div class="grp"><div class="gl">Тема</div><div class="skins">${app.pub().themes.map((t) => `
        <button type="button" class="skin${p.skin === t.id ? ' sel' : ''}" data-skin="${t.id}">
          <div class="pv" style="background:${esc(t.preview)}"><i style="background:${esc(t.accent)}"></i></div>
          <span>${esc(t.name)}<small>${esc(t.desc)}</small></span></button>`).join('')}</div></div>
      <div class="grp"><div class="gl">Тло</div>${seg('bgSeg', p.background, [['scene', 'Живий пейзаж'], ['still', 'Пейзаж без руху'], ['solid', 'Однотонне']])}</div>
      <div class="grp"><div class="gl">Поведінка</div>
        ${tgl('pWx', p.weather_react, 'Пейзаж реагує на погоду', 'хмари, дощ, сніг на вершинах, туман')}
        ${tgl('pSky', p.sky_by_time, 'Небо за часом доби', 'ранок, день, вечір, ніч і зірки')}</div>`;
  },
  layout(p) {
    const zone = (z) => {
      const ids = p.layout[z] || [];
      const reg = W.all();
      const avail = W.allowed(z).filter((w) => !ids.includes(w.id));
      return `<div class="zbox"><div class="zt">${icon(z === 'login' ? 'i-lock' : 'i-layout')}${ZONES[z].title}</div><div class="zs">${ZONES[z].sub}</div>
        ${ids.map((id, i) => `<div class="wrow"><span class="grip">⋮⋮</span><span class="nm">${esc(reg[id]?.title || id)}</span>
          <button type="button" data-mv="${z}|${i}|-1" ${i === 0 ? 'disabled' : ''} title="Вище">${icon('i-up')}</button>
          <button type="button" data-mv="${z}|${i}|1" ${i === ids.length - 1 ? 'disabled' : ''} title="Нижче">${icon('i-down')}</button>
          <button type="button" data-rm="${z}|${i}" title="Прибрати">${icon('i-x')}</button></div>`).join('') || '<div class="mute" style="font-size:.85em;padding:.4em 0">порожньо</div>'}
        <div class="addw"><select id="add-${z}" aria-label="Віджет для зони ${ZONES[z].title}">${avail.length ? avail.map((w) => `<option value="${w.id}">${esc(w.title)}</option>`).join('') : '<option value="">усі віджети вже тут</option>'}</select>
        <button class="btn" type="button" data-add="${z}" ${avail.length ? '' : 'disabled'}>${icon('i-plus')}Додати</button></div></div>`;
    };
    return `<h3>Макет і віджети</h3><p class="lead">Кожен блок є окремим віджетом із папки <code>widgets/</code>. Новий віджет, скопійований туди, з'явиться у списку «Додати».</p>
      <div class="zones">${zone('login')}${zone('side')}</div>
      <div class="grp" style="margin-top:1.4em"><div class="gl">Текст віджета «Нотатка»</div>
      <div class="fld" style="max-width:40em"><textarea id="pNote" rows="4">${esc(p.note)}</textarea></div></div>`;
  },
  saver(p) {
    return `<h3>Заставка</h3><p class="lead">Вмикається на екрані входу через ${app.pub().saver_after_min} хв без дій. Час задається для всього екрана у <code>config.yaml</code>.</p>
      ${tgl('pFx', p.saver.fx, 'Погодні ефекти', 'дощ, сніг, блискавки, туман, світлячки: на заставці, на екрані входу і ледь помітно в панелі')}
      ${tgl('pClock', p.saver.clock, 'Великий годинник на заставці')}
      <div style="margin-top:1em"><button class="btn" type="button" id="showSaver">${icon('i-moon')}Показати зараз</button></div>`;
  },
  weather(p) {
    const cfg = app.pub().weather;
    return `<h3>Погода</h3><p class="lead">Дані з Open-Meteo, оновлюються раз на 15 хвилин. Порожнє місто означає значення за замовчуванням (${esc(cfg.city)}).</p>
      <form id="wxForm"><div class="fld">Місто<input id="wxCity" value="${esc(p.weather.city)}" placeholder="${esc(cfg.city)}"></div>
      <div class="fld">Одиниці<select id="wxUnits"><option value="">як за замовчуванням</option><option value="c" ${p.weather.units === 'c' ? 'selected' : ''}>°C, м/с</option><option value="f" ${p.weather.units === 'f' ? 'selected' : ''}>°F, mph</option></select></div>
      <button class="btn" type="submit">Зберегти</button></form>`;
  },
  launch(p) {
    return `<h3>Запуск систем</h3><p class="lead">Що відбувається, коли натискаєш ▶ на системі.</p>
      <div class="grp"><div class="gl">Відеокарта за замовчуванням</div>${seg('gpuSeg', p.launch.gpu, [['auto', 'Вільна дискретна на моєму моніторі'], ['igpu', 'Вбудована']])}</div>
      ${tgl('pAsk', p.launch.ask, 'Питати перед запуском', 'вимкни, і ▶ запускатиме одразу на відеокарті за замовчуванням')}`;
  },
  services(p) {
    const list = app.services();
    return `<h3>Вебсервіси</h3><p class="lead">Що показувати на вкладці «Вебсервіси». Сам список береться з Caddy і оновлюється автоматично.</p>
      <div class="svclist">${list.map((s) => `<label><img src="/icons/${esc(s.icon || s.key)}.svg" alt="" onerror="this.style.visibility='hidden'">${esc(s.name)}
        <input type="checkbox" data-hide="${esc(s.key)}" ${p.hidden_services.includes(s.key) ? '' : 'checked'}></label>`).join('')}</div>`;
  },
  account(p) {
    return `<h3>Обліковий запис</h3><p class="lead">Пароль і права керуються в Proxmox. Тут лише те, що стосується цього екрана.</p>
      <div class="grp"><div class="gl">Колір аватарки</div><div class="avpick">${AVATARS.map((a, i) => `<button type="button" style="background:${a}" aria-pressed="${p.avatar === i}" data-av="${i}" title="Колір ${i + 1}"></button>`).join('')}</div></div>
      ${tgl('pShow', p.show_on_login, 'Показувати мене на екрані входу', 'інакше входити через «Інший користувач»')}`;
  },
};

function bind(p) {
  $$('[data-skin]', $('#settingsBox')).forEach((b) => b.onclick = () => save({ skin: b.dataset.skin }));
  const segBind = (id, fn) => $$(`#${id} button`).forEach((b) => b.onclick = () => { fn(b.dataset.v); render(); });
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
    try { await app.weather(true); toast('Погоду оновлено'); app.applyPrefs({ relayout: true }); } catch (err) { toast(err.message, true); }
  });
  $$('[data-av]').forEach((b) => b.onclick = () => { save({ avatar: +b.dataset.av }); render(); });
  $$('[data-hide]').forEach((c) => c.onchange = () => {
    const k = c.dataset.hide;
    save({ hidden_services: c.checked ? p.hidden_services.filter((x) => x !== k) : [...p.hidden_services, k] });
  });
  const lay = () => JSON.parse(JSON.stringify(p.layout));
  $$('[data-mv]').forEach((b) => b.onclick = () => {
    const [z, i, d] = b.dataset.mv.split('|'); const L = lay(); const a = L[z]; const j = +i + +d;
    [a[i], a[j]] = [a[j], a[i]]; save({ layout: L }, { relayout: true }); render();
  });
  $$('[data-rm]').forEach((b) => b.onclick = () => {
    const [z, i] = b.dataset.rm.split('|'); const L = lay(); L[z].splice(+i, 1); save({ layout: L }, { relayout: true }); render();
  });
  $$('[data-add]').forEach((b) => b.onclick = () => {
    const z = b.dataset.add, v = $('#add-' + z).value;
    if (v) { const L = lay(); (L[z] ||= []).push(v); save({ layout: L }, { relayout: true }); render(); }
  });
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
      ${SECTIONS.map(([id, ic, t]) => `<button type="button" data-sp="${id}" aria-selected="${id === current}">${icon(ic)}${t}</button>`).join('')}
      <span class="sp"></span><span class="saved" id="savedNote">зміни зберігаються самі</span>
    </nav>
    <div class="scont"><button class="chipbtn sclose" type="button" id="sClose">${icon('i-x')}Закрити</button>${views[current](p)}</div>`;
  $$('[data-sp]').forEach((b) => b.onclick = () => { current = b.dataset.sp; render(); });
  $('#sClose').onclick = () => app.go('dash');
  bind(p);
}

export function open(section) {
  if (section) current = section;
  render();
}

export function init(a) { app = a; }
