// Translations. Dictionaries live in web/i18n/<code>.json; adding a file adds a language.
// Widgets bring their own strings (module.i18n) under the "w.<id>." prefix.
//
//   t('login.who')                        plain string
//   t('launch.cores', { n: 12 })          "{n} ядер" / "12 cores"; plural forms via {one, few, many, other}
//   <b data-i18n="dash.web"></b>          static markup, filled by apply()
//   data-i18n-title / data-i18n-placeholder / data-i18n-aria

const LOCALES = { uk: 'uk-UA', en: 'en-GB' };
let lang = 'en';
let dict = {};
const extra = {}; // lang -> { key: value } contributed by widgets
const cache = {};
const listeners = new Set();

export const current = () => lang;
export const locale = () => LOCALES[lang] || lang;

export async function load(code) {
  if (!cache[code]) {
    const r = await fetch(`/i18n/${code}.json`, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`language ${code} not found`);
    cache[code] = await r.json();
  }
  return cache[code];
}

export async function setLang(code) {
  let d;
  try { d = await load(code); } catch { code = 'en'; d = await load('en'); }
  if (code === lang && dict === d) return false;
  lang = code;
  dict = d;
  document.documentElement.lang = code;
  apply();
  listeners.forEach((fn) => fn(code));
  return true;
}

export function onChange(fn) { listeners.add(fn); }

// Widget strings: extend('w.weather.', { uk: {...}, en: {...} })
export function extend(prefix, byLang) {
  for (const [code, strings] of Object.entries(byLang || {})) {
    extra[code] ||= {};
    for (const [k, v] of Object.entries(strings)) extra[code][prefix + k] = v;
  }
}

function lookup(key) {
  return dict[key] ?? extra[lang]?.[key] ?? cache.en?.[key] ?? extra.en?.[key];
}

export function t(key, vars = {}) {
  let v = lookup(key);
  if (v === undefined) return key;
  if (typeof v === 'object') {
    const form = new Intl.PluralRules(locale()).select(vars.n ?? 0);
    v = v[form] ?? v.other ?? Object.values(v)[0];
  }
  return String(v).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}

export function apply(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
  root.querySelectorAll('[data-i18n-title]').forEach((e) => { e.title = t(e.dataset.i18nTitle); });
  root.querySelectorAll('[data-i18n-placeholder]').forEach((e) => { e.placeholder = t(e.dataset.i18nPlaceholder); });
  root.querySelectorAll('[data-i18n-aria]').forEach((e) => { e.setAttribute('aria-label', t(e.dataset.i18nAria)); });
}
