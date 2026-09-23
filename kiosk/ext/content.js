// Two jobs:
//  1. In the menu page: a bridge, so the menu can open/switch/close service tabs (window.postMessage <-> extension).
//  2. In every service page: a dock ("⌂ Menu", open services, reload, close) reachable by mouse, Tab or Alt+Q.
(() => {
  if (window.top !== window) return;
  const MENU = 'http://127.0.0.1:8900/';
  const send = (msg) => chrome.runtime.sendMessage(msg);

  if (location.href.startsWith(MENU)) {
    window.addEventListener('message', async (e) => {
      if (e.source !== window || !e.data?.pvehomelab) return;
      const res = await send(e.data.pvehomelab).catch((err) => ({ error: String(err) }));
      window.postMessage({ pvehomelabReply: e.data.id, res }, location.origin);
    });
    chrome.runtime.onMessage.addListener((m) => {
      if (m.type === 'tabs') window.postMessage({ pvehomelabTabs: m.tabs }, location.origin);
    });
    const hello = () => window.postMessage({ pvehomelabBridge: true }, location.origin);
    document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', hello) : hello();
    window.addEventListener('message', (e) => { if (e.source === window && e.data?.pvehomelabPing) hello(); });
    return;
  }

  // The dock follows the menu's language (stored by the background when the menu changes it).
  const TEXT = {
    uk: { menu: '⌂ Меню', menu_title: 'Повернутись у меню (сервіс лишиться відкритим)', reload: '↻ Оновити', reload_title: 'Оновити сторінку',
          close: '✕ Закрити', close_title: 'Закрити цей сервіс', help: '← → вибір · Enter · Esc назад' },
    en: { menu: '⌂ Menu', menu_title: 'Back to the menu (the service stays open)', reload: '↻ Reload', reload_title: 'Reload the page',
          close: '✕ Close', close_title: 'Close this service', help: '← → select · Enter · Esc back' },
  };
  let tabs = [];
  let returnTo = null; // where focus was on the site before the dock took it
  const host = document.createElement('div');
  host.style.cssText = 'all:initial;position:fixed;left:12px;bottom:12px;z-index:2147483647';
  const root = host.attachShadow({ mode: 'closed' });
  root.innerHTML = `
    <style>
      .dock{font:500 14px/1.2 system-ui,sans-serif;color:#fff;display:flex;align-items:center;gap:6px;padding:6px;
        background:rgba(14,19,27,.92);border:1px solid rgba(255,255,255,.16);border-radius:14px;backdrop-filter:blur(12px);
        box-shadow:0 10px 30px -10px rgba(0,0,0,.7);max-width:calc(100vw - 24px);overflow-x:auto}
      .more{display:contents}
      .dock.mini{opacity:.55} .dock.mini:hover{opacity:1}
      .dock.mini .more{display:none}
      button{all:unset;cursor:pointer;display:flex;align-items:center;gap:7px;padding:8px 12px;border-radius:10px;white-space:nowrap;
        color:#e8edf3;max-width:220px;overflow:hidden;text-overflow:ellipsis}
      button:hover{background:rgba(255,255,255,.1)}
      button:focus{outline:2px solid #ff8a3d;outline-offset:1px;background:rgba(255,138,61,.22)}
      button.cur{background:rgba(255,255,255,.14)}
      button.home{background:linear-gradient(180deg,#ffc15e,#ff8a3d);color:#1f0e02;font-weight:700}
      button.home:focus{outline-color:#fff}
      button.close{color:#ffb3b3}
      img{width:16px;height:16px;flex:none}
      .sep{width:1px;align-self:stretch;background:rgba(255,255,255,.15);margin:2px}
      .hint{font:500 11px system-ui;opacity:.65;padding:0 6px;white-space:nowrap}
      .dock.mini .hint.full{display:none} .dock:not(.mini) .hint.short{display:none}
      .t{overflow:hidden;text-overflow:ellipsis}
    </style>
    <div class="dock mini" role="toolbar" aria-label="PVE Homelab">
      <button class="home" data-a="menu" data-t="menu"></button>
      <span class="more">
        <span class="sep"></span><span id="tabs" style="display:contents"></span><span class="sep"></span>
        <button data-a="reload" data-t="reload"></button>
        <button class="close" data-a="close" data-t="close"></button>
      </span>
      <span class="hint short">Alt+Q</span><span class="hint full" data-t="help"></span>
    </div>`;
  const dock = root.querySelector('.dock');
  function localize(lang) {
    const d = TEXT[lang] || TEXT.en;
    root.querySelectorAll('[data-t]').forEach((e) => {
      e.textContent = d[e.dataset.t];
      if (d[e.dataset.t + '_title']) e.title = d[e.dataset.t + '_title'];
    });
  }
  localize((navigator.language || 'en').slice(0, 2));
  chrome.storage.local.get('lang').then((v) => v.lang && localize(v.lang)).catch(() => {});
  const buttons = () => [...root.querySelectorAll('button')].filter((b) => b.getClientRects().length);
  const inDock = () => document.activeElement === host;

  function renderTabs() {
    const box = root.querySelector('#tabs');
    box.textContent = '';
    for (const t of tabs) {
      const b = document.createElement('button');
      b.dataset.a = 'switch'; b.dataset.id = t.id;
      if (t.active) b.className = 'cur';
      b.title = t.url;
      if (t.icon) { const i = document.createElement('img'); i.src = t.icon; b.append(i); }
      const s = document.createElement('span'); s.className = 't'; s.textContent = t.title; b.append(s);
      box.append(b);
    }
  }

  function openDock() {
    if (!inDock()) returnTo = document.activeElement;
    dock.classList.remove('mini');
    send({ cmd: 'list' }).then((l) => { if (Array.isArray(l)) { tabs = l; renderTabs(); } });
    buttons()[0]?.focus();
  }

  function closeDock() {
    dock.classList.add('mini');
    root.activeElement?.blur();
    const back = returnTo && returnTo.isConnected && returnTo !== host ? returnTo : document.body;
    returnTo = null;
    back?.focus?.();
  }

  function act(b) {
    const a = b.dataset.a;
    closeDock();
    if (a === 'switch') send({ cmd: 'switch', id: +b.dataset.id });
    else send({ cmd: a });
  }

  root.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) act(b); });
  root.addEventListener('focusin', () => { if (dock.classList.contains('mini')) openDock(); });

  // Registered at document_start, so this runs before the site's own keyboard handlers.
  window.addEventListener('keydown', (e) => {
    if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyQ') {
      e.preventDefault(); e.stopImmediatePropagation();
      inDock() ? closeDock() : openDock();
      return;
    }
    if (!inDock()) return;
    const list = buttons(), i = list.indexOf(root.activeElement);
    let handled = true;
    if (e.key === 'ArrowRight' || (e.key === 'Tab' && !e.shiftKey)) list[(i + 1) % list.length]?.focus();
    else if (e.key === 'ArrowLeft' || (e.key === 'Tab' && e.shiftKey)) list[(i - 1 + list.length) % list.length]?.focus();
    else if (e.key === 'Home') list[0]?.focus();
    else if (e.key === 'End') list[list.length - 1]?.focus();
    else if (e.key === 'Escape') closeDock();
    else if (e.key === 'Enter' || e.key === ' ') { if (list[i]) act(list[i]); }
    else handled = false;
    if (handled) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);

  chrome.runtime.onMessage.addListener((m) => {
    if (m.type === 'dock') inDock() ? closeDock() : openDock();
    if (m.type === 'tabs') { tabs = m.tabs; renderTabs(); }
    if (m.type === 'lang') localize(m.lang);
  });
  const mount = () => (document.body || document.documentElement).appendChild(host);
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', mount) : mount();
})();
