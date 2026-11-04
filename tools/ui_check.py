#!/usr/bin/env python3
"""Browser checks of the menu, run against the demo in a headless Chrome/Chromium.

    python tools/ui_check.py --start-demo                 # starts its own demo on :8911
    python tools/ui_check.py --url http://127.0.0.1:8900  # a demo that is already running
    python tools/ui_check.py --start-demo --only alerts,console

Every check signs in like a person would (clicks, keys), looks at the page and prints PASS or
FAIL; the exit code is the number of failed checks. JavaScript errors and unhandled rejections
are collected through DevTools for the whole run, so a page reload does not hide them. The demo
user's settings are saved first and put back at the end; the demo world is reset between checks.
Needs aiohttp (requirements-demo.txt) and Chrome or Chromium.
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import aiohttp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = ("const q = (m, p, b) => fetch(p + (p.includes('?') ? '&' : '?') + 'seat=igpu', {method: m, "
       "headers: {'Content-Type': 'application/json', 'X-Seat': 'igpu'}, body: b && JSON.stringify(b)}).then((r) => r.json());")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_browser(given):
    for b in ([given] if given else []) + ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        path = shutil.which(b) or (b if os.path.exists(b) else None)
        if path:
            return path
    sys.exit("Chrome or Chromium not found; pass --browser")


class Page:
    """A tab driven over the DevTools protocol."""

    def __init__(self, ws):
        self.ws, self.n, self.pending, self.errors = ws, 0, {}, []

    async def reader(self):
        async for m in self.ws:
            d = json.loads(m.data)
            if "id" in d and d["id"] in self.pending:
                self.pending.pop(d["id"]).set_result(d.get("result", {}))
            elif d.get("method") == "Runtime.exceptionThrown":
                x = d["params"]["exceptionDetails"]
                self.errors.append((x.get("exception") or {}).get("description") or x.get("text"))

    async def send(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send_json({"id": self.n, "method": method, "params": params})
        return await fut

    async def js(self, body, wait=0.0):
        r = await self.send("Runtime.evaluate", expression=f"(async () => {{ {body} }})()", awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"].get("text"))
        if wait:
            await asyncio.sleep(wait)
        return r.get("result", {}).get("value")

    async def key(self, key, code=0, text=None):
        await self.send("Input.dispatchKeyEvent", type="keyDown" if text else "rawKeyDown", key=key, text=text or "", windowsVirtualKeyCode=code)
        await self.send("Input.dispatchKeyEvent", type="keyUp", key=key, windowsVirtualKeyCode=code)

    async def until(self, body, timeout=5.0):
        """Poll a JS expression (body returns a value) until it is truthy."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                v = await self.js(body)
            except RuntimeError:  # the page is between documents: nothing to read yet
                v = None
            if v:
                return v
            await asyncio.sleep(0.2)
        return None


class Run:
    def __init__(self, page, base):
        self.p, self.base, self.failed, self.passed = page, base, [], 0
        self.prefs = None  # the demo user's settings at the start; every check starts from them

    def check(self, name, ok, detail=""):
        # an empty list or None as detail is worth seeing too: show anything but the default ""
        print(f"  {'PASS' if ok else 'FAIL'} {name}{f'  ({detail!r})' if detail != '' and not ok else ''}")
        if ok:
            self.passed += 1
        else:
            self.failed.append(name)

    async def open(self, user="ihor@pve"):
        """Fresh page, demo world reset, signed in as `user` (None: stay on the sign-in screen)."""
        p = self.p
        # No session left from the previous check: otherwise the page signs itself in on load
        # while the check signs in again, and the later of the two lands on the dashboard.
        for attempt in (1, 2):
            await p.send("Network.clearBrowserCookies")
            await p.send("Page.navigate", url=self.base)
            if await p.until("return document.querySelector('[data-scr=login]')?.hidden === false && !!document.querySelector('[data-user]')", 15):
                break
            try:
                seen = await p.js("return [document.readyState, [...document.querySelectorAll('body > .scr')].filter(e => !e.hidden).map(e => e.dataset.scr), location.href];")
            except RuntimeError as e:
                seen = str(e)
            print(f"  (sign-in screen not shown, attempt {attempt}: {seen})")
        else:
            raise RuntimeError("the sign-in screen did not show up")
        await p.js(API + "await q('POST', '/api/demo/reset', {}); await q('POST', '/api/demo/world', {weather: 'partly', update: false});")
        if self.prefs:
            # Checks change settings (hidden services, order, layout): put them back, or one check
            # silently changes what the next one sees.
            await p.js(API + "await q('POST', '/api/login', {user: 'ihor@pve', password: 'x'}); "
                       f"await q('PUT', '/api/prefs', {json.dumps(self.prefs)}); await q('POST', '/api/logout');")
        if user:
            await p.js(f"document.querySelector('[data-user=\"{user}\"]').click();", 0.3)
            await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
            if not await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false && document.querySelectorAll('.sys .play').length > 0", 15):
                raise RuntimeError(f"{user} did not get to the dashboard")

    async def screen(self):
        return await self.p.js("return [...document.querySelectorAll('body > .scr')].filter(e => !e.hidden).map(e => e.dataset.scr)[0];")


# ---------------------------------------------------------------- checks

async def guests(r):
    p = r.p
    await r.open()
    await p.js("document.querySelector('[data-ptab=guests]').click();", 0.6)
    await p.js("document.querySelector('#guestrows [data-act*=\"|shutdown|\"]').click();", 0.5)
    r.check("Shut down asks for confirmation", await p.js("return !document.querySelector('#confirmLayer').hidden;"))
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    r.check("Esc closes the confirmation only", await p.js("return document.querySelector('#confirmLayer').hidden;") and await r.screen() == "dash")
    await p.js("document.querySelector('#guestrows [data-act*=\"|start|\"]').click();")
    toast = await p.until("const t = document.querySelector('#toast'); return !t.hidden && [t.textContent, t.classList.contains('bad')];")
    r.check("Start reports the command was sent", toast and not toast[1], toast)


async def logout(r):
    p = r.p
    await r.open()
    await p.js("document.querySelector('#logoutBtn').click();")
    await p.until("return !document.querySelector('[data-scr=login]').hidden", 5)
    n = await p.js("return [document.querySelectorAll('#svcgrid .svc').length, document.querySelectorAll('#guestrows [data-guest]').length, document.querySelectorAll('.sys .play').length];")
    r.check("sign-out clears the previous user's dashboard", n == [0, 0, 0], n)
    r.check("sign-out hides the bell", await p.js("return document.querySelector('#alertBell').hidden;"))


async def widgets(r):
    p = r.p
    await r.open()
    # The services-health widget reads its data through the app, not over HTTP: its failure is
    # fully under the check's control (an HTTP widget may be served from the shared cache).
    await p.js("""window.__fail = true;
        window.__app = {services: () => { if (window.__fail) throw new Error('services down'); return [{name: 'X', status: 'running'}]; }};
        const W = await import('/core/widgets.js'); W.renderZone('side', ['svchealth'], {app: window.__app, opts: {}});""", 1.0)
    box = "document.querySelector('[data-zone=side] [data-w=svchealth]')"
    r.check("a failed widget offers Try again", await p.js(f"return !!{box}?.querySelector('.wretry');"))
    await p.js(f"window.__fail = false; {box}?.querySelector('.wretry')?.click();", 1.0)
    r.check("Try again loads it", await p.js(f"return !!{box} && !{box}.querySelector('.werr') && {box}.textContent.includes('1/1');"))
    await p.js("window.__rf = window.fetch; window.__host = 0; const f = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/api/host')) window.__host++; return f(u, o); };")
    await p.js("const W = await import('/core/widgets.js'); W.renderZone('side', ['host', 'network'], {app: {}, opts: {}});", 1.0)
    n = await p.js("return window.__host;")
    r.check("host and network widgets share one request", n == 1, n)
    await p.js("window.fetch = window.__rf;")


async def toasts(r):
    p = r.p
    await r.open()
    await p.js("const ui = await import('/core/ui.js'); ui.toast('first'); ui.toast('second');")
    seen = []
    for _ in range(60):
        txt = await p.js("const t = document.querySelector('#toast'); return t.hidden ? '' : t.textContent;")
        if txt and (not seen or seen[-1] != txt):
            seen.append(txt)
        if seen[-1:] == ["second"]:
            break
        await asyncio.sleep(0.2)
    r.check("messages wait their turn", seen[-2:] == ["first", "second"], seen)


async def offline(r):
    p = r.p
    await r.open()
    await p.js("window.__rf = window.fetch; window.fetch = () => Promise.reject(new TypeError('down')); const { api } = await import('/core/api.js'); try { await api.get('/api/guests'); } catch {}", 0.5)
    r.check("a banner tells the backend is gone", await p.js("return !document.querySelector('#offline').hidden;"))
    # the page reloads by itself once the backend answers again
    await p.js("window.fetch = window.__rf;")


async def dialogs_aria(r):
    p = r.p
    await r.open(None)
    ok = await p.js("return ['#confirmLayer .confirm', '#helpLayer .confirm', '#alertsLayer .confirm', '[data-layer=launch] .modal']"
                    ".every(s => document.querySelector(s).getAttribute('aria-modal') === 'true')"
                    " && document.querySelector('#toast').getAttribute('aria-live') === 'polite';")
    r.check("dialogs are modal for assistive tech, toasts are announced", ok)


async def alerts(r):
    p = r.p
    await r.open()
    n = await p.until("const b = document.querySelector('#alertBell'); return !b.hidden && b.querySelector('.n').textContent;", 6)
    r.check("the bell counts what needs a look", n == "1", n)
    await p.js("const b = document.querySelector('#alertBell'); b.focus(); b.click();", 0.4)
    items = await p.js("return [...document.querySelectorAll('#alertsList li')].map(l => l.textContent);")
    r.check("its dialog lists the stale backups", items and "backup" in items[0], items)
    for key, code in (("Tab", 9), ("ArrowDown", 40)):
        await p.key(key, code)
        await asyncio.sleep(0.2)
        inside = await p.js("return !!document.activeElement?.closest('#alertsLayer');")
        r.check(f"{key} keeps focus inside the dialog", inside)
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    st = await p.js("return [document.querySelector('#alertsLayer').hidden, document.activeElement?.id];")
    r.check("Esc closes it and focus goes back to the bell", st == [True, "alertBell"], st)


async def failed_update(r):
    p = r.p
    fake = """window.__rf = window.fetch; window.fetch = (u, o) => /\\/api\\/update(\\?|$)/.test(String(u))
      ? Promise.resolve(new Response(JSON.stringify({enabled: true, available: false, can_apply: true,
          last: {ok: false, rolled_back: true, ref: 'v0.5.0', error: 'no start', time: %d}}), {status: 200}))
      : window.__rf(u, o);""" % int(time.time())
    seen = []
    for _ in range(2):
        await r.open(None)
        await p.js(fake)
        await p.js("document.querySelector('[data-user=\"ihor@pve\"]').click();", 0.3)
        await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
        got = await p.until("const t = document.querySelector('#toast'); return !t.hidden && t.textContent.includes('v0.5.0') && t.textContent;", 6)
        seen.append(got)
    r.check("an admin is told about a failed update", bool(seen[0]), seen[0])
    r.check("…once only", not seen[1], seen[1])


async def settings_focus(r):
    p = r.p
    await r.open()
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=dash]').click();", 0.8)
    r.check("Settings open", await r.screen() == "dash" and await p.js("return !document.querySelector('[data-layer=settings]').hidden;"))
    for attr in ("data-omv", "data-vis"):
        before = await p.js(f"const b = [...document.querySelectorAll('[{attr}]:not([disabled])')][2]; b.focus(); b.click(); return b.getAttribute('{attr}');", 1.0)
        after = await p.js(f"const a = document.activeElement; return a?.getAttribute('{attr}') || (a && a.tagName + '.' + a.className);")
        r.check(f"focus stays on {attr} after a change", before and before == after, f"{before} -> {after}")


async def console(r):
    p = r.p
    await r.open()
    await p.js("window.__opened = []; window.open = (u) => { window.__opened.push(String(u)); return null; };")
    await p.js("window.__posts = []; const f = window.fetch; window.fetch = (u, o) => { if ((o || {}).method === 'POST') window.__posts.push(String(u)); return f(u, o); };")
    await p.js("document.querySelector('[data-ptab=guests]').click();", 0.6)
    await p.js("document.querySelector('#guestrows [data-console^=\"lxc|\"]').click();", 2.0)
    posts = await p.js("return window.__posts;")
    r.check("a container's console is asked for inside the menu", any("/api/console/" in x and "type=lxc" in x for x in posts), posts)
    r.check("without a console the menu goes back to the dashboard", await r.screen() == "dash")


async def launch(r):
    p = r.p
    await r.open()
    await p.js("document.querySelector('[data-sys=\"0\"]').click();", 1.0)
    r.check("a system's card opens the launch dialog", await p.js("return !!document.querySelector('#mOpts [data-gpu].sel');"))
    await p.js("document.querySelector('#mStart').click();")
    steps = await p.until("return document.querySelectorAll('#mSteps li').length;", 3)
    r.check("launching shows its steps", (steps or 0) >= 2, steps)
    back = await p.until("return !document.querySelector('[data-scr=dash]').hidden && document.querySelector('[data-layer=launch]').hidden;", 12)
    r.check("…and comes back to the dashboard", back)
    running = await p.js(API + "return (await q('GET', '/api/systems')).filter(s => s.status === 'running').length;")
    r.check("the system is running", running == 1, running)


async def search(r):
    p = r.p
    await r.open()
    # the services arrive after the systems: type only once they are on screen
    await p.until("return document.querySelectorAll('#svcgrid .svc').length > 5", 15)
    await p.js("document.querySelector('#svcgrid .svc').focus();")
    for ch in "jelly":
        await p.key(ch, 0, ch)
    names = await p.until("const n = [...document.querySelectorAll('#svcgrid .svc .n')].map(n => n.textContent); return n.length === 1 && n;", 3)
    seen = await p.js("return [document.querySelector('#svcSearch').value, [...document.querySelectorAll('#svcgrid .svc .n')].map(n => n.textContent)];")
    r.check("typing on the dashboard narrows the services", names == ["Jellyfin"], repr(seen))
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    n = await p.js("return [document.querySelectorAll('#svcgrid .svc').length, document.querySelector('#svcSearch').hidden];")
    r.check("Esc clears the search", n[0] > 5 and n[1], n)


async def reorder(r):
    p = r.p
    await r.open()
    first = await p.js("const b = document.querySelector('#svcgrid .svc'); b.focus(); return b.dataset.key;")
    await p.send("Input.dispatchKeyEvent", type="rawKeyDown", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39, modifiers=1)
    await p.send("Input.dispatchKeyEvent", type="keyUp", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39, modifiers=1)
    await asyncio.sleep(0.6)
    keys = await p.js("return [...document.querySelectorAll('#svcgrid .svc')].slice(0, 2).map(b => b.dataset.key);")
    r.check("Alt+→ moves a service one place right", keys and keys[1] == first, keys)
    r.check("…and focus moves with it", await p.js("return document.activeElement?.dataset.key;") == first)
    saved = await p.js(API + "return (await q('GET', '/api/me')).prefs.order.services.slice(0, 2);")
    r.check("the new order is saved", saved and saved[1] == first, saved)


async def guest_table(r):
    p = r.p
    await r.open()
    await p.js("document.querySelector('[data-ptab=guests]').click();", 0.6)
    await p.js("document.querySelector('[data-sort=cpu]').click();", 0.3)
    state = await p.js("""const rows = [...document.querySelectorAll('#guestrows tr')];
        const cpu = rows.map(r => r.children[4]?.textContent.trim()).filter(x => x && x !== '—').map(x => parseFloat(x));
        return [document.querySelector('th[data-col=cpu]').getAttribute('aria-sort'), cpu];""")
    r.check("CPU header sorts the busiest first", state[0] == "descending" and state[1] == sorted(state[1], reverse=True) and len(state[1]) > 2, state)
    await p.js("document.querySelector('[data-sort=cpu]').click();", 0.3)
    r.check("…and the other way on a second click", await p.js("return document.querySelector('th[data-col=cpu]').getAttribute('aria-sort');") == "ascending")
    await p.js("document.querySelector('[data-sort=vmid]').click(); document.querySelector('#guestrows [data-guest]').focus();", 0.3)
    for ch in "jelly":
        await p.key(ch, 0, ch)
    names = await p.until("const n = [...document.querySelectorAll('#guestrows .gname')].map(b => b.textContent.trim()); return n.length === 1 && n;", 3)
    r.check("typing on the guests tab filters the guests", names == ["jellyfin"], names)
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    n = await p.js("return document.querySelectorAll('#guestrows .gname').length;")
    r.check("Esc clears the guest filter", n > 5, n)

    # a guest's history
    await p.js("document.querySelector('#guestrows [data-guest]').click();")
    charts = await p.until("return !document.querySelector('#guestLayer').hidden && document.querySelectorAll('#gCharts .chart path').length;", 5)
    r.check("a guest's name opens its history with charts", (charts or 0) >= 3, charts)
    extra = await p.until("const x = document.querySelector('#gExtra').textContent; return x.includes('before-upgrade') && x;", 5)
    r.check("…with its snapshots and last backup", extra and "Last backup" in extra and "with RAM" in extra, extra)
    # the first guest by ID (VM 100) is stopped in the demo: its charts must not show old values as "now"
    head = await p.js("return [...document.querySelectorAll('#gCharts .gch span')].map(s => s.textContent);")
    r.check("a stopped guest reads as off now, not its last values", head and all("off now" in h for h in head), head)
    await p.js("document.querySelector('#gRange [data-range=week]').click();")
    wk = await p.until("return document.querySelector('#gRange [data-range=week]').getAttribute('aria-pressed') === 'true' && document.querySelectorAll('#gCharts .chart').length === 3;", 5)
    r.check("the week range loads", wk)
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    st = await p.js("return [document.querySelector('#guestLayer').hidden, document.activeElement?.classList.contains('gname'), document.querySelector('[data-pane=guests]').hidden];")
    r.check("Esc closes the history, focus back on the guest", st == [True, True, False], st)


async def service_tabs(r):
    p = r.p
    await r.open()
    # What the kiosk extension sends when service tabs are open next to the menu.
    await p.js("postMessage({pvehomelabTabs: [{id: 7, title: 'Jellyfin', url: 'https://jellyfin.home.example', icon: ''}]}, location.origin);", 0.5)
    tabs = await p.js("return [...document.querySelectorAll('#openTabs .otab')].map(t => [t.textContent.trim(), !!t.querySelector('[data-tab=\"7\"] svg'), !!t.querySelector('[data-tabx=\"7\"]')]);")
    r.check("open service tabs show in the top bar", tabs == [["Jellyfin", True, True]], tabs)


async def misc(r):
    p = r.p
    await r.open(None)
    await p.js(API + "await q('POST', '/api/demo/world', {update: true});")
    await p.js("document.querySelector('[data-user=\"ihor@pve\"]').click();", 0.3)
    await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
    pill = await p.until("const x = document.querySelector('#updPill'); return !x.hidden && x.textContent.trim();", 6)
    r.check("the update pill names the new version", pill and "v9.9.0" in pill, pill)
    await p.js("document.body.focus();")
    await p.key("?", 0, "?")
    await asyncio.sleep(0.4)
    r.check("? opens the keyboard help", await p.js("return !document.querySelector('#helpLayer').hidden && document.querySelectorAll('#helpTable tr').length > 5;"))
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    r.check("Esc closes it", await p.js("return document.querySelector('#helpLayer').hidden;"))
    icon = await p.js("return document.querySelector('[data-wx-icon]').getAttribute('src');")
    code = await p.js(f"return (await fetch({json.dumps(icon or '')})).status;")
    r.check("the weather icon exists", icon and code == 200, f"{icon} {code}")


CHECKS = {"guests": guests, "logout": logout, "widgets": widgets, "toasts": toasts, "offline": offline,
          "aria": dialogs_aria, "alerts": alerts, "update": failed_update, "focus": settings_focus,
          "console": console, "launch": launch, "search": search, "order": reorder, "guests_table": guest_table, "tabs": service_tabs, "misc": misc}


# ---------------------------------------------------------------- driver

async def main(a):
    demo, demo_state = None, None
    base = a.url
    if a.start_demo:
        port = free_port()
        py = os.path.join(ROOT, ".demo", "venv", "bin", "python")
        # Its own clean settings: the same start here and in CI, and the usual demo is left alone.
        demo_state = tempfile.mkdtemp(prefix="pvehomelab-uicheck-state-")
        demo = subprocess.Popen([py if os.path.exists(py) else sys.executable, os.path.join(ROOT, "demo.py"), "--no-browser",
                                 "--lang", "en", "--port", str(port), "--state", demo_state],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
    base = base.rstrip("/") + "/?seat=igpu"
    dbg = free_port()
    prof = tempfile.mkdtemp(prefix="pvehomelab-uicheck-")
    flags = ["--headless=new", "--hide-scrollbars", "--mute-audio", "--no-first-run",
             f"--remote-debugging-port={dbg}", f"--user-data-dir={prof}", "--window-size=1600,900"]
    if a.no_sandbox:  # CI runners whose kernel forbids Chrome's sandbox
        flags.append("--no-sandbox")
    browser = subprocess.Popen([find_browser(a.browser), *flags, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as http:
            for _ in range(100):
                try:
                    async with http.get(base) as resp:
                        if resp.status == 200:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.3)
            else:
                sys.exit(f"the menu does not answer at {base}")
            page = None
            for _ in range(60):
                try:
                    async with http.get(f"http://127.0.0.1:{dbg}/json") as resp:
                        page = next(t for t in await resp.json() if t["type"] == "page")
                    break
                except Exception:
                    await asyncio.sleep(0.3)
            async with http.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                p = Page(ws)
                reader = asyncio.ensure_future(p.reader())
                await p.send("Runtime.enable")
                await p.send("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1, mobile=False)
                if a.cpu_throttle > 1:  # behave like a slow CI runner
                    await p.send("Emulation.setCPUThrottlingRate", rate=a.cpu_throttle)
                r = Run(p, base)
                await r.open()
                saved = r.prefs = await p.js(API + "return (await q('GET', '/api/me')).prefs;")
                try:
                    for name in a.only or CHECKS:
                        print(name)
                        try:
                            await CHECKS[name](r)
                        except Exception as e:
                            r.check(f"{name} ran", False, e)
                    r.check("no JavaScript errors", not p.errors, p.errors[:3])
                    if a.shot:
                        shot = await p.send("Page.captureScreenshot", format="png")
                        with open(a.shot, "wb") as f:
                            f.write(base64.b64decode(shot["data"]))
                finally:
                    try:  # the demo user's own settings back, whatever the checks did
                        await r.open()
                        await p.js(API + f"await q('PUT', '/api/prefs', {json.dumps(saved)}); await q('POST', '/api/demo/reset', {{}});")
                    except Exception as e:
                        r.check("demo settings restored", False, e)
                    reader.cancel()
        print(f"\n{r.passed} passed, {len(r.failed)} failed" + (f": {', '.join(r.failed)}" if r.failed else ""))
        return len(r.failed)
    finally:
        browser.kill()
        shutil.rmtree(prof, ignore_errors=True)
        if demo:
            demo.terminate()
            demo.wait(10)
        if demo_state:
            shutil.rmtree(demo_state, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8900", help="a running demo (default %(default)s)")
    ap.add_argument("--start-demo", action="store_true", help="start a demo of this checkout on a free port")
    ap.add_argument("--browser", help="Chrome or Chromium binary")
    ap.add_argument("--no-sandbox", action="store_true", help="run Chrome without its sandbox (CI only)")
    ap.add_argument("--only", type=lambda s: [x for x in s.split(",") if x], help=f"comma-separated: {','.join(CHECKS)}")
    ap.add_argument("--shot", help="save a screenshot of the last page to this PNG")
    ap.add_argument("--cpu-throttle", type=float, default=1, help="slow the page's CPU down N times, like a slow CI runner")
    args = ap.parse_args()
    if args.only and set(args.only) - set(CHECKS):
        sys.exit(f"unknown checks: {set(args.only) - set(CHECKS)}")
    sys.exit(min(asyncio.run(main(args)), 100))
