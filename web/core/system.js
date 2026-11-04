// Settings → System (admins): the host's settings, as the server describes them
// (backend/pvehomelab/settings.py). What is changed here goes to settings.yaml next to
// config.yaml and wins over it; "Back to the file" takes a setting out again.

import { $, $$, icon, esc, toast, t } from './ui.js';

let form = null;          // {groups, settings, restart, not_in_menu}
let group = 'general';
let query = '';
let errors = {};          // path -> message, from the last save
let loading = null;

const label = (s) => t(`cfg.${s.path}`);
const hint = (s) => { const k = `cfg.${s.path}_hint`; const v = t(k); return v === k ? '' : v; };
const choiceLabel = (s, c) => { const k = `cfg.${s.path}.${c}`; const v = t(k); return v === k ? c : v; };
const fid = (path) => 'sys-' + path.replace(/[^a-z0-9]/gi, '_');

let formFor = null;      // whose form it is: another admin signs in, it is asked again

export function reset() { form = null; errors = {}; query = ''; formFor = null; }

export function ensure(app, rerender) {
  if (form && formFor !== app.me()?.id) reset();
  if (form || loading) return !!form;
  formFor = app.me()?.id;
  loading = app.api.get('/api/system/settings')
    .then((f) => { form = f; })
    .catch((e) => toast(e.message, true))
    .finally(() => { loading = null; rerender(); });
  return false;
}

function source(s) {
  if (s.source === 'menu') {
    return `<span class="sys-src menu">${esc(t('cfg.src_menu'))}</span>
      <button type="button" class="lnk" data-sys-reset="${esc(s.path)}">${icon('i-restart')}<span>${esc(t(s.file_value === undefined || s.file_value === null ? 'cfg.reset_default' : 'cfg.reset_file'))}</span></button>`;
  }
  return s.source === 'file' ? `<span class="sys-src">${esc(t('cfg.src_file'))}</span>` : '';
}

function field(s) {
  const id = fid(s.path);
  const v = s.value;
  switch (s.kind) {
    case 'bool':
      return `<span class="sw"><input type="checkbox" id="${id}" data-sys="${esc(s.path)}" ${v ? 'checked' : ''}><i></i></span>`;
    case 'choice':
      return `<div class="seg" data-sys-seg="${esc(s.path)}">${s.choices.map((c) => `<button type="button" data-v="${esc(c)}" aria-pressed="${c === v}">${esc(choiceLabel(s, c))}</button>`).join('')}</div>`;
    case 'int':
      return `<input id="${id}" type="number" data-sys="${esc(s.path)}" value="${v ?? ''}" ${s.min !== undefined ? `min="${s.min}"` : ''} ${s.max !== undefined ? `max="${s.max}"` : ''}>`;
    case 'str':
      return `<input id="${id}" data-sys="${esc(s.path)}" value="${esc(v ?? '')}" spellcheck="false">`;
    case 'list':
      return `<textarea id="${id}" data-sys="${esc(s.path)}" rows="${Math.min(8, Math.max(2, (v || []).length + 1))}" spellcheck="false" placeholder="${esc(t('cfg.one_per_line'))}">${esc((v || []).join('\n'))}</textarea>`;
    case 'rows':
    case 'map': {
      const rows = s.kind === 'map' ? Object.entries(v || {}).map(([k, r]) => ({ _key: k, ...r })) : (v || []);
      const cols = (s.kind === 'map' ? [{ key: '_key', required: true }] : []).concat(s.fields);
      const head = cols.map((c) => `<th>${esc(t(`cfg.f.${c.key}`))}</th>`).join('') + '<th></th>';
      const body = rows.map((r, i) => `<tr data-row="${i}">${cols.map((c) => `<td><input data-col="${esc(c.key)}" value="${esc(r[c.key] ?? '')}" spellcheck="false" aria-label="${esc(t(`cfg.f.${c.key}`))}"></td>`).join('')}
        <td><button type="button" class="chipbtn" data-row-del="${i}" aria-label="${esc(t('cfg.row_del'))}">${icon('i-x')}</button></td></tr>`).join('');
      return `<div class="sys-table" data-sys-table="${esc(s.path)}"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
        <div class="sys-tbtns"><button type="button" class="chipbtn" data-row-add>${icon('i-plus')}<span>${esc(t('cfg.row_add'))}</span></button>
        <button type="button" class="chipbtn" data-row-save>${esc(t('cfg.row_save'))}</button></div></div>`;
    }
    default:
      return '';
  }
}

function item(s) {
  const err = errors[s.path];
  const wide = ['list', 'rows', 'map'].includes(s.kind);
  return `<div class="sys-item${wide ? ' wide' : ''}" data-path="${esc(s.path)}">
    <div class="sys-label"><label for="${fid(s.path)}">${esc(label(s))}</label>
      ${hint(s) ? `<small>${esc(hint(s))}</small>` : ''}
      <span class="sys-meta">${source(s)}${s.restart ? `<span class="sys-src warn">${esc(t('cfg.needs_restart'))}</span>` : ''}<code>${esc(s.path)}</code></span>
      ${err ? `<div class="sys-err" role="alert">${esc(err)}</div>` : ''}</div>
    <div class="sys-field">${field(s)}</div></div>`;
}

export function view() {
  if (!form) return `<h3>${esc(t('set.s.system'))}</h3><p class="mute">…</p>`;
  const q = query.trim().toLowerCase();
  const shown = form.settings.filter((s) => (q ? `${label(s)} ${hint(s)} ${s.path}`.toLowerCase().includes(q) : s.group === group));
  const restart = form.restart ? `<div class="sys-restart" role="status">${icon('i-restart')}<span>${esc(t(`cfg.restart_${form.restart}`))}</span>
    <button type="button" class="btn" id="sysRestart">${esc(t('cfg.restart_now'))}</button></div>` : '';
  return `<h3>${esc(t('set.s.system'))}</h3>
    <p class="lead">${esc(t('cfg.lead'))}</p>
    ${restart}
    <div class="sys-bar"><input id="sysSearch" type="search" value="${esc(query)}" placeholder="${esc(t('cfg.search'))}" aria-label="${esc(t('cfg.search'))}">
      ${q ? '' : `<div class="seg" id="sysGroups">${form.groups.filter((g) => form.settings.some((s) => s.group === g)).map((g) => `<button type="button" data-v="${g}" aria-pressed="${g === group}">${esc(t(`cfg.g.${g}`))}</button>`).join('')}</div>`}</div>
    <div class="sys-list">${shown.map(item).join('') || `<p class="mute">${esc(t('cfg.nothing'))}</p>`}</div>
    <p class="mute sys-note">${esc(t('cfg.elsewhere'))}</p>`;
}

async function send(app, rerender, body, path) {
  try {
    form = await app.api.put('/api/system/settings', body);
    delete errors[path];
    $('#savedNote') && ($('#savedNote').textContent = t('set.saved'));
  } catch (e) {
    if (e.status === 400) {
      // the server names the setting it refused; the reply carries the reasons
      errors[path] = /^Error 400$/.test(e.message) ? t('cfg.invalid') : `${t('cfg.invalid')}: ${e.message}`;
    } else toast(e.message, true);
  }
  rerender();
}

function tableValue(s, box) {
  const rows = $$('tbody tr', box).map((tr) => Object.fromEntries($$('[data-col]', tr).map((i) => [i.dataset.col, i.value.trim()])));
  const keep = rows.filter((r) => Object.values(r).some(Boolean));
  if (s.kind === 'map') return Object.fromEntries(keep.map(({ _key, ...r }) => [_key, Object.fromEntries(Object.entries(r).filter(([, v]) => v))]));
  return keep.map((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v)));
}

export function bind(app, rerender) {
  if (!form) return;
  const byPath = Object.fromEntries(form.settings.map((s) => [s.path, s]));
  const set = (path, value) => send(app, rerender, { set: { [path]: value } }, path);
  $('#sysSearch').oninput = (e) => {
    query = e.target.value;
    const pos = e.target.selectionStart;
    rerender();
    const el = $('#sysSearch');
    el.focus();
    el.setSelectionRange(pos, pos);
  };
  $$('#sysGroups button').forEach((b) => (b.onclick = () => { group = b.dataset.v; rerender(); }));
  $$('[data-sys]').forEach((el) => {
    const s = byPath[el.dataset.sys];
    el.onchange = () => {
      if (s.kind === 'bool') return set(s.path, el.checked);
      if (s.kind === 'int') return set(s.path, el.value === '' && s.null ? null : Number(el.value));
      if (s.kind === 'list') return set(s.path, el.value.split('\n').map((x) => x.trim()).filter(Boolean));
      return set(s.path, el.value);
    };
  });
  $$('[data-sys-seg]').forEach((g) => $$('button', g).forEach((b) => (b.onclick = () => set(g.dataset.sysSeg, b.dataset.v))));
  $$('[data-sys-reset]').forEach((b) => (b.onclick = () => send(app, rerender, { reset: [b.dataset.sysReset] }, b.dataset.sysReset)));
  $$('[data-sys-table]').forEach((box) => {
    const s = byPath[box.dataset.sysTable];
    $('[data-row-save]', box).onclick = () => set(s.path, tableValue(s, box));
    $('[data-row-add]', box).onclick = () => {
      const cols = $$('thead th', box).length - 1;
      const keys = (s.kind === 'map' ? ['_key'] : []).concat(s.fields.map((f) => f.key));
      const tr = document.createElement('tr');
      tr.innerHTML = keys.map((k) => `<td><input data-col="${esc(k)}" spellcheck="false" aria-label="${esc(t(`cfg.f.${k}`))}"></td>`).join('') + '<td></td>';
      if (cols) $('tbody', box).appendChild(tr);
      $('input', tr).focus();
    };
    $$('[data-row-del]', box).forEach((b) => (b.onclick = () => { b.closest('tr').remove(); set(s.path, tableValue(s, box)); }));
  });
  const r = $('#sysRestart');
  if (r) {
    r.onclick = async () => {
      r.disabled = true;
      try {
        await app.api.post('/api/system/restart');
        form.restart = null;
        toast(t('cfg.restarting'));
      } catch (e) { toast(e.message, true); }
      rerender();
    };
  }
}
