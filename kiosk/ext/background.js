// Services live in tabs next to the menu tab. Kiosk mode shows only the active tab,
// so "switching windows" is just activating a tab.
const MENU = 'http://127.0.0.1:8900/';
const isMenu = (t) => (t.url || t.pendingUrl || '').startsWith(MENU);

async function menuTab() {
  return (await chrome.tabs.query({})).find(isMenu);
}

async function list() {
  const tabs = await chrome.tabs.query({});
  return tabs.filter((t) => !isMenu(t)).map((t) => ({
    id: t.id, title: t.title || t.url, url: t.url || t.pendingUrl || '', icon: t.favIconUrl || '', active: t.active,
  }));
}

async function activate(tab) {
  if (!tab) return;
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
}

async function open(url) {
  const origin = new URL(url).origin;
  const found = (await chrome.tabs.query({})).find((t) => !isMenu(t) && (t.url || '').startsWith(origin));
  if (found) return activate(found);
  const m = await menuTab();
  const tab = await chrome.tabs.create({ url, active: true, windowId: m?.windowId });
  await activate(tab);
}

async function broadcast() {
  const m = await menuTab();
  const tabs = await list();
  for (const t of await chrome.tabs.query({})) {
    chrome.tabs.sendMessage(t.id, { type: 'tabs', tabs, menu: m?.id }).catch(() => {});
  }
}

async function handle(msg, sender) {
  switch (msg?.cmd) {
    case 'menu': return activate(await menuTab());
    case 'list': return list();
    case 'open': return open(msg.url);
    case 'switch': return activate(await chrome.tabs.get(msg.id));
    case 'reload': return chrome.tabs.reload(msg.id ?? sender.tab.id);
    case 'close': {
      const id = msg.id ?? sender.tab?.id;
      const t = id && (await chrome.tabs.get(id).catch(() => null));
      if (t && !isMenu(t)) {
        const wasActive = t.active;
        await chrome.tabs.remove(id);
        if (wasActive) await activate(await menuTab());
      }
      return true;
    }
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  handle(msg, sender).then((r) => reply(r ?? true), (e) => reply({ error: String(e) }));
  return true;
});

chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== 'show-dock') return;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (tab) chrome.tabs.sendMessage(tab.id, { type: 'dock' }).catch(() => {});
});

// The kiosk opens the menu before this extension is ready, so its bridge script is missing there.
// Reload the menu once when the extension (re)starts with the browser.
async function reloadMenu() {
  for (const t of await chrome.tabs.query({})) if (isMenu(t)) chrome.tabs.reload(t.id);
}
chrome.runtime.onStartup.addListener(reloadMenu);
chrome.runtime.onInstalled.addListener(reloadMenu);

chrome.tabs.onCreated.addListener(broadcast);
chrome.tabs.onRemoved.addListener(broadcast);
chrome.tabs.onActivated.addListener(broadcast);
chrome.tabs.onUpdated.addListener((_id, info) => { if (info.title || info.favIconUrl || info.status === 'complete') broadcast(); });
