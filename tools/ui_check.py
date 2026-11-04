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
# Settings shows "…" while a list (My designs, My widgets) loads, then draws the section again:
# a file chosen in the install input before that lands in an input that is gone.
LOADED = "![...document.querySelectorAll('.scont p.mute')].some((e) => e.textContent.trim() === '…')"

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
                fut, method = self.pending.pop(d["id"])
                # A protocol error must not pass for an empty answer: a file set on a node the page
                # has just redrawn ("Could not find node with given id") would go nowhere unnoticed.
                if "error" in d:
                    fut.set_exception(RuntimeError(f"{method}: {d['error'].get('message')}"))
                else:
                    fut.set_result(d.get("result", {}))
            elif d.get("method") == "Runtime.exceptionThrown":
                x = d["params"]["exceptionDetails"]
                self.errors.append((x.get("exception") or {}).get("description") or x.get("text"))

    async def send(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = (fut, method)
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
        self.designs_dir = None  # the demo's own designs folder, when this run started the demo
        self.widgets_dir = None  # …and its widgets folder

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


async def tfa_signin(r):
    """A second factor with the keyboard alone: the keypad takes the focus, digits type, the sixth signs in."""
    p = r.p
    await r.open(None)
    await p.js("document.querySelector('[data-user=\"olena@pve\"]').click();", 0.3)
    await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
    shown = await p.until("return !document.querySelector('#tfaBox').hidden && document.activeElement?.dataset.k === '1'", 5)
    r.check("after the password the code is asked, the keypad has the focus", shown)
    r.check("the password row is out of the way", await p.js("return getComputedStyle(document.querySelector('.pwrow')).display === 'none';"))
    for d in "000000":
        await p.key(d, 48, d)
    err = await p.until("const e = document.querySelector('#loginErr'); return !e.hidden && e.textContent;", 5)
    r.check("a wrong code says so and the code is asked again", err and await p.js("return !document.querySelector('#tfaBox').hidden && document.querySelector('#tfaCode').value === '';"), err)
    await p.js("document.querySelector('[data-tfa-kind=recovery]').click();", 0.3)
    r.check("a recovery key can be typed instead", await p.js("return document.querySelector('#tfaPad').hidden && document.activeElement?.id === 'tfaCode';"))
    await p.js("document.querySelector('[data-tfa-kind=totp]').click();", 0.3)
    for d in "123456":
        await p.key(d, 48 + int(d), d)
    r.check("the sixth digit signs in", await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false", 8))
    await p.js("document.querySelector('#logoutBtn').click();")
    await p.until("return !document.querySelector('[data-scr=login]').hidden", 5)
    await p.js("document.querySelector('[data-user=\"olena@pve\"]').click();", 0.3)
    await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
    await p.until("return !document.querySelector('#tfaBox').hidden", 5)
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    r.check("Esc goes back to the password", await p.js("return document.querySelector('#tfaBox').hidden && document.activeElement?.id === 'pw';"))


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


async def quiet_faults(r):
    """What is no fault of the page stays out of the error journal: a chosen clock design that was
    removed since (the digital one shows), and a widget whose request was cut (the banner shows it)."""
    p = r.p
    await r.open()
    await p.js(API + "await q('DELETE', '/api/logs'); await q('PUT', '/api/prefs', {...(await q('GET', '/api/me')).prefs, clock: 'uicheck-gone'});")
    await p.send("Page.navigate", url=r.base)
    await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false && document.querySelectorAll('.sys .play').length > 0", 15)
    await asyncio.sleep(1.5)
    shown = await p.js("return document.querySelector('[data-clock]').dataset.clockk;")
    logged = await p.js(API + "return (await q('GET', '/api/logs')).entries.filter(e => e.source.startsWith('client:')).map(e => e.msg);")
    r.check("a removed clock design: the digital one, nothing in the journal", shown == "digital" and logged == [], [shown, logged])
    await p.js("window.__rf = window.fetch; window.__urls = [];"
               "window.fetch = (u) => { window.__urls.push(String(u)); return Promise.reject(new TypeError('Failed to fetch')); };"
               "const W = await import('/core/widgets.js'); const box = document.createElement('div'); document.body.append(box);"
               "W.mount(box, 'disks', 'side', {opts: {}});", 1.0)
    st = await p.js("return [!!document.querySelector('.werr'), window.__urls.filter(u => u.includes('/api/client-log')).length];")
    await p.js("window.fetch = window.__rf;")
    r.check("a widget whose request was cut says so, but records no fault", st == [True, 0], st)


async def dialogs_aria(r):
    p = r.p
    await r.open(None)
    ok = await p.js("return ['#confirmLayer .confirm', '#helpLayer .confirm', '#alertsLayer .confirm', '#nodeUpdLayer .confirm', '[data-layer=launch] .modal']"
                    ".every(s => document.querySelector(s).getAttribute('aria-modal') === 'true')"
                    " && document.querySelector('#toast').getAttribute('aria-live') === 'polite';")
    r.check("dialogs are modal for assistive tech, toasts are announced", ok)


async def alerts(r):
    p = r.p
    await r.open()
    n = await p.until("const b = document.querySelector('#alertBell'); return !b.hidden && b.querySelector('.n').textContent;", 6)
    # stale backups, and Nextcloud's site: its container is stopped
    r.check("the bell counts what needs a look", n == "2", n)
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


async def system_settings(r):
    """Settings → System: admins only; a change shows where it comes from and goes back to the file."""
    p = r.p
    await r.open("guest@pve")
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    r.check("someone who isn't an admin has no System section", await p.js("return !document.querySelector('[data-sp=system]');"))
    await r.open()
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=system]').click();")
    shown = await p.until("return document.querySelectorAll('.sys-item').length > 2 && document.querySelectorAll('#sysGroups button').length", 6)
    r.check("an admin gets the host's settings in groups", shown and shown > 5, shown)
    await p.js("[...document.querySelectorAll('#sysGroups button')].find(b => b.dataset.v === 'alerts').click();", 0.5)
    await p.js("const i = document.querySelector('[data-sys=\"alerts.storage_pct\"]'); i.value = '77'; i.dispatchEvent(new Event('change'));")
    badge = await p.until("return document.querySelector('[data-path=\"alerts.storage_pct\"] .sys-src.menu')?.textContent", 5)
    r.check("a change is saved and marked as made here", badge, badge)
    await p.js("const i = document.querySelector('[data-sys=\"alerts.temp_c\"]'); i.value = '500'; i.dispatchEvent(new Event('change'));")
    err = await p.until("return document.querySelector('[data-path=\"alerts.temp_c\"] .sys-err')?.textContent", 5)
    r.check("a wrong value is refused next to the setting", err, err)
    await p.js("document.querySelector('[data-sys-reset=\"alerts.storage_pct\"]').click();")
    back = await p.until("return !document.querySelector('[data-path=\"alerts.storage_pct\"] .sys-src.menu') && document.querySelector('[data-sys=\"alerts.storage_pct\"]').value", 5)
    r.check("Back to config.yaml takes the change out", back == "90", back)
    await p.js("const s = document.querySelector('#sysSearch'); s.value = 'caddy'; s.dispatchEvent(new Event('input'));", 0.5)
    found = await p.js("return [...document.querySelectorAll('.sys-item')].map(e => e.dataset.path);")
    want = {"caddy.ct", "caddy.admin", "caddy.prefer_suffix", "caddy.hide"}
    r.check("search finds settings across groups", found and want <= set(found) and not any(x.startswith("alerts") for x in found), found)


async def components(r):
    """Settings → System → Components: a part switched off leaves the page at once."""
    p = r.p
    await r.open()
    r.check("the weather is in the top bar", await p.js("return getComputedStyle(document.querySelector('.tw[data-needs=weather]')).display !== 'none';"))
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=system]').click();")
    await p.until("return document.querySelectorAll('#sysGroups button').length", 6)
    await p.js("[...document.querySelectorAll('#sysGroups button')].find(b => b.dataset.v === 'components').click();", 0.5)
    await p.js("const c = document.querySelector('[data-sys=\"features.weather\"]'); c.checked = false; c.dispatchEvent(new Event('change'));")
    gone = await p.until("return getComputedStyle(document.querySelector('.tw[data-needs=weather]')).display === 'none'", 5)
    r.check("switched off, the weather leaves the top bar", gone)
    offered = await p.js("const W = await import('/core/widgets.js'); return W.allowed('side').map(w => w.id);")
    r.check("and its widget is no longer offered", offered and "weather" not in offered and "host" in offered, offered)
    await p.js("const c = document.querySelector('[data-sys=\"features.weather\"]'); c.checked = true; c.dispatchEvent(new Event('change'));")
    back = await p.until("return getComputedStyle(document.querySelector('.tw[data-needs=weather]')).display !== 'none'", 5)
    r.check("switched on again, it is back", back)


async def interface(r):
    """Settings → Interface: size, calm, parts of the dashboard, 12 hours."""
    p = r.p
    await r.open()
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=ui]').click();", 0.5)
    before = await p.js("return parseFloat(getComputedStyle(document.querySelector('.A')).fontSize);")
    await p.js("document.querySelector('#uiScale [data-v=\"140\"]').click();", 0.5)
    after = await p.js("return parseFloat(getComputedStyle(document.querySelector('.A')).fontSize);")
    r.check("a larger size makes everything larger", after > before * 1.3, (before, after))
    await p.js("const c = document.querySelector('#uiCalm'); c.checked = true; c.dispatchEvent(new Event('change'));", 0.3)
    r.check("calm stops the animations", await p.js("return document.body.classList.contains('calm');"))
    await p.js("const c = document.querySelector('#uiSecSystems'); c.checked = false; c.dispatchEvent(new Event('change'));", 0.3)
    r.check("systems can leave the dashboard", await p.js("return getComputedStyle(document.querySelector('.sysrail')).display === 'none';"))
    await p.js("document.querySelector('#uiClock [data-v=\"12\"]').click();", 1.2)
    clock = await p.js("return document.querySelector('[data-clock]')?.textContent || '';")
    r.check("12 hours shows no hour above 12", clock and int(clock.split(':')[0].strip() or 0) <= 12, clock)
    saved = await p.js(API + "return (await q('GET', '/api/me')).prefs.ui;", 0.8)
    r.check("and it is saved", saved and saved["scale"] == 140 and saved["motion"] == "calm" and saved["sections"]["systems"] is False, saved)


async def guest_resources(r):
    """A guest's dialog: memory, cores, start at boot, tags; saved through Proxmox with your rights."""
    p = r.p
    await r.open()
    await p.js("document.querySelector('[data-ptab=guests]').click();", 0.6)
    await p.js("document.querySelector('#guestrows [data-guest*=\"201\"]')?.click() || [...document.querySelectorAll('#guestrows [data-guest]')].find(b => b.textContent.includes('jellyfin')).click();")
    ok = await p.until("return !document.querySelector('#guestLayer').hidden && !!document.querySelector('#grMem')", 6)
    r.check("a guest's dialog has its resources", ok)
    await p.js("document.querySelector('#gRes').open = true; document.querySelector('#grMem').value = '6'; document.querySelector('#grCores').value = '5';"
               "document.querySelector('#grOnboot').checked = true; document.querySelector('#grTags').value = 'media, home';"
               "document.querySelector('#gResForm').requestSubmit();")
    msg = await p.until("return document.querySelector('#grMsg')?.textContent", 5)
    saved = await p.js(API + "return await q('GET', '/api/guests/lxc/201/config');")
    r.check("saving writes them", saved and saved["memory"] == 6144 and saved["cores"] == 5 and saved["onboot"] and saved["tags"] == ["media", "home"], (msg, saved))
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    await r.open("guest@pve")
    await p.js("document.querySelector('[data-ptab=guests]').click();", 0.6)
    await p.js("[...document.querySelectorAll('#guestrows [data-guest]')].find(b => b.textContent.includes('jellyfin')).click();")
    dis = await p.until("return document.querySelector('#grMem')?.disabled && !document.querySelector('#gResForm [type=submit]')", 6)
    r.check("without the rights the fields are read-only", dis)


async def settings_copy(r):
    """Settings → About: a copy of the settings, downloaded and put back by parts."""
    p = r.p
    await r.open()
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=about]').click();", 0.8)
    href = await p.js("return document.querySelector('#copyGet')?.getAttribute('href');")
    r.check("an admin can download a copy", href and href.startswith("/api/backup/export"), href)
    await p.js(API + "await q('PUT', '/api/prefs', {skin: 'forest'});")
    await p.js("window.__copy = await (await fetch(document.querySelector('#copyGet').href)).blob();"
               + API + "await q('PUT', '/api/prefs', {skin: 'graphite'});")
    await p.js("const dt = new DataTransfer(); dt.items.add(new File([window.__copy], 'copy.tar.gz', {type: 'application/gzip'}));"
               "const i = document.querySelector('#copyFile'); i.files = dt.files; i.dispatchEvent(new Event('change'));")
    parts = await p.until("return [...document.querySelectorAll('[data-copy-part]')].map(c => c.dataset.copyPart + ':' + c.checked);", 5)
    r.check("choosing a copy shows its parts, ticked", parts and "users:true" in parts, parts)
    await p.js("document.querySelector('#copyApply').click();", 0.5)
    await p.js("document.querySelector('#confirmLayer .btn:not(.ghost)')?.click() || document.querySelector('#confirmYes')?.click();", 0.3)
    skin = None
    for _ in range(20):
        await asyncio.sleep(0.4)
        try:
            skin = await p.js(API + "return (await q('GET', '/api/me')).prefs.skin;")
        except RuntimeError:
            continue
        if skin == "forest":
            break
    r.check("putting it back brings the settings back", skin == "forest", skin)
    await p.until("return document.readyState === 'complete' && !!document.querySelector('[data-scr]')", 8)


async def away(r):
    """A system on this monitor: the page stands aside, keys do nothing but both Ctrl, which go back
    and forth between the menu and the system."""
    p = r.p
    await r.open()
    await p.js(API + "const s = await q('GET', '/api/systems'); const vm = s.find(x => x.name === 'ubuntu-desktop');"
               "const gpu = vm.options.find(o => o.mode === 'passthrough').pci; window.__job = await q('POST', '/api/launch', {vmid: vm.vmid, gpu});")
    shown = await p.until("return document.querySelector('[data-scr=away]')?.hidden === false && document.querySelector('#awayName').textContent", 10)
    r.check("a system on this monitor puts the page aside", shown == "ubuntu-desktop", shown)
    await p.key("j", 74, "j")
    await asyncio.sleep(0.3)
    r.check("keys typed meanwhile do nothing", await r.screen() == "away" and not await p.js("return !!document.querySelector('#searchBox:not([hidden])') || !!(document.activeElement && document.activeElement.value);"))
    async def both():
        await p.send("Input.dispatchKeyEvent", type="rawKeyDown", key="Control", code="ControlLeft", windowsVirtualKeyCode=17, modifiers=2)
        await p.send("Input.dispatchKeyEvent", type="rawKeyDown", key="Control", code="ControlRight", windowsVirtualKeyCode=17, modifiers=2, location=2)
        await p.send("Input.dispatchKeyEvent", type="keyUp", key="Control", code="ControlRight", windowsVirtualKeyCode=17, location=2)
        await p.send("Input.dispatchKeyEvent", type="keyUp", key="Control", code="ControlLeft", windowsVirtualKeyCode=17)
    await both()
    r.check("both Ctrl bring the menu back", await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false", 5))
    await both()
    r.check("and from the menu go to the system again", await p.until("return document.querySelector('[data-scr=away]')?.hidden === false", 5))
    await p.js(API + "const s = await q('GET', '/api/systems'); const vm = s.find(x => x.name === 'ubuntu-desktop'); await q('POST', `/api/guests/qemu/${vm.vmid}/stop`);")
    r.check("the system stopping brings the menu back", await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false", 15))


async def launch_input(r):
    """Keyboard and mouse go with the monitor, and both Ctrl in the system bring both back."""
    p = r.p
    await r.open()
    await p.js("document.querySelector('.play[data-key=\"100\"]').click();", 1.0)   # ubuntu-desktop
    tick = await p.js("const c = document.querySelector('#mInput'); return c && c.checked;")
    r.check("the launch dialog offers keyboard and mouse, ticked by default", tick)
    await p.js("document.querySelector('#mStart').click();")
    steps = await p.until("return [...document.querySelectorAll('#mSteps li')].map(l => l.textContent).join(' | ');", 3)
    r.check("their step is among the launch steps", steps and ("Keyboard" in steps or "Клавіатура" in steps), steps)
    r.check("the page stands aside", await p.until("return document.querySelector('[data-scr=away]')?.hidden === false", 10))
    # the keyboard follows a second after the monitor (QEMU's monitor answers once the VM runs)
    log = None
    for _ in range(20):
        log = await p.js(API + "return (await q('GET', '/api/seat'));")
        if log and log["input"] == log["shows"] != "menu":
            break
        await asyncio.sleep(0.3)
    r.check("the seat says the system has the keyboard", log and log["input"] == log["shows"] and log["shows"] != "menu", log)
    await p.js(API + "await q('POST', '/api/demo/input-release', {});")
    r.check("both Ctrl in the system bring the menu back", await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false", 8))


async def input_settings(r):
    """Settings → Systems: the host's keyboards and mice, and the VM's own left alone."""
    p = r.p
    await r.open()
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.8)
    await p.js("document.querySelector('[data-sp=systems]').click();", 0.3)
    rows = await p.until("return [...document.querySelectorAll('.inlist li')].map(l => l.textContent.replace(/\\s+/g, ' ').trim());", 5)
    r.check("the host's input devices are listed", rows and len(rows) >= 4, rows)
    r.check("the VM's own keyboard is shown as its own", rows and any("102" in x for x in rows), rows)
    await p.js("const c = document.querySelector('[data-inunit=\"1-4\"]'); c.checked = false; c.dispatchEvent(new Event('change'));", 1.0)
    picked = await p.js(API + "const f = await q('GET', '/api/system/settings'); return f.settings.find(s => s.path === 'input.devices').value;")
    r.check("an admin leaves the gamepad out", picked and "1-4" not in picked and "1-3" in picked, picked)


async def gamepad(r):
    """A gamepad drives the menu: the D-pad moves, A opens, B closes, RB switches tabs."""
    p = r.p
    await r.open()
    await p.js("window.__pad = {buttons: Array.from({length: 17}, () => ({pressed: false})), axes: [0, 0]};"
               "navigator.getGamepads = () => [window.__pad]; window.dispatchEvent(new Event('gamepadconnected'));", 0.3)

    async def tap(i):
        await p.js(f"window.__pad.buttons[{i}].pressed = true;", 0.35)   # a frame may take a while headless
        await p.js(f"window.__pad.buttons[{i}].pressed = false;", 0.35)
    await p.js("document.querySelector('.sys .play').focus();")
    before = await p.js("return document.activeElement?.dataset.key;")
    await tap(15)
    after = await p.js("return document.activeElement?.dataset.key;")
    r.check("the D-pad moves between systems", before and after and before != after, (before, after))
    await tap(0)
    r.check("A opens the launch dialog", await p.until("return document.querySelector('[data-layer=launch]').hidden === false", 3))
    await tap(1)
    r.check("B closes it", await p.until("return document.querySelector('[data-layer=launch]').hidden === true", 3))
    await tap(5)
    r.check("RB switches to the next tab", await p.js("return document.querySelector('[data-ptab=guests]').getAttribute('aria-selected') === 'true';"))
    await tap(9)
    r.check("Start opens the settings", await p.until("return document.querySelector('[data-layer=settings]').hidden === false", 3))
    await p.js("document.querySelector('#sClose').click();", 0.3)


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
    # a start on the GPU of this monitor: the monitor shows the system and the page stands aside
    back = await p.until("return document.querySelector('[data-layer=launch]').hidden && "
                         "(!document.querySelector('[data-scr=away]').hidden || !document.querySelector('[data-scr=dash]').hidden);", 12)
    r.check("…and the dialog closes (the page stands aside while the system has the monitor)", back)
    await p.js(API + "await q('POST', '/api/seat/focus', {to: 'menu'});", 0.8)
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


async def my_designs(r):
    p = r.p
    theme = os.path.join(tempfile.mkdtemp(prefix="pvehomelab-uicheck-design-"), "uicheck-neon.css")
    with open(theme, "w", encoding="utf-8") as f:
        f.write("/*\n * @kind theme\n * @name.en UI check neon\n * @name.uk Неон перевірки\n */\n"
                ".A[data-skin=\"uicheck-neon\"],.A [data-skin=\"uicheck-neon\"]{--acc:#00e5ff}\n")
    open_mine = ("document.querySelector('.top [data-go=settings]').click();"
                 "await new Promise(r => setTimeout(r, 500));"
                 "document.querySelector('[data-lookmine]').click();")
    await r.open()
    await p.js(open_mine)
    ok = await p.until(f"return !!document.querySelector('#designPick') && {LOADED} && "
                       "document.querySelector('.mylist, .scont .mute:not(.dinstall .mute)') !== null;", 8)
    r.check("an admin sees My designs with an install button", ok)
    # choose the file in the real file input, as a person would through the file dialog
    doc = await p.send("DOM.getDocument")
    node = await p.send("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#designFiles")
    await p.send("DOM.setFileInputFiles", files=[theme], nodeId=node["nodeId"])
    back = await p.until("return !document.querySelector('[data-layer=settings]')?.hidden && "
                         "!!document.querySelector('#lookMine') && "
                         "[...document.querySelectorAll('.mylist li')].map(l => l.textContent).join('|').includes('UI check neon');", 12)
    r.check("installing reloads back to My designs, listing the new one", back)
    themes = await p.js(API + "return (await q('GET', '/api/public')).themes.map(t => t.id);")
    r.check("…and it is offered as a theme", "uicheck-neon" in (themes or []), themes)
    await p.js("document.querySelector('[data-rmdesign^=\"themes|uicheck-neon\"]').click();", 0.4)
    await p.js("document.querySelector('#cYes').click();")
    gone = await p.until("return !!document.querySelector('#lookMine') && "
                         "!document.querySelector('[data-rmdesign]') && document.querySelectorAll('.mylist li').length === 0;", 12)
    r.check("removing it reloads back with the list empty", gone)
    await r.open("guest@pve")
    await p.js(open_mine)
    guest = await p.until("return !document.querySelector('#designPick') && document.querySelector('.scont').textContent.includes('admins');", 5)
    r.check("someone without Sys.Modify is told installing is for admins", guest)
    shutil.rmtree(os.path.dirname(theme), ignore_errors=True)


async def design_pack(r):
    """A theme with the background and clock of yours it brings is one row in My designs, removed as one;
    whoever wore it gets the built-in look back, with nothing in the error journal."""
    p = r.p
    if not r.designs_dir:
        r.check("design_pack (needs --start-demo: it writes into the demo's designs folder)", True)
        return
    files = {("themes", "uicheck-pack.css"): '/*\n * @name.en Pack check\n * @background uicheck-vec\n * @clock uicheck-tty\n */\n'
                                             '.A[data-skin="uicheck-pack"],.A [data-skin="uicheck-pack"]{--acc:#ff00ff}\n',
             ("backgrounds", "uicheck-vec.css"): '/*\n * @name.en Vec check\n */\n.bgx[data-k="uicheck-vec"]{background:#123}\n',
             ("clocks", "uicheck-tty.js"): "/*\n * @name.en Tty check\n */\nexport const css = '';\nexport function render(el) { el.textContent = 'TTY'; }\n"}
    for (kind, name), text in files.items():
        os.makedirs(os.path.join(r.designs_dir, kind), exist_ok=True)
        with open(os.path.join(r.designs_dir, kind, name), "w", encoding="utf-8") as f:
            f.write(text)
    try:
        await r.open()
        await p.js(API + "await q('DELETE', '/api/logs'); await q('PUT', '/api/prefs', {...(await q('GET', '/api/me')).prefs,"
                   " skin: 'uicheck-pack', background: 'uicheck-vec', clock: 'uicheck-tty'});")
        await p.send("Page.navigate", url=r.base)
        await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false && document.querySelectorAll('.sys .play').length > 0", 15)
        await p.js("document.querySelector('.top [data-go=settings]').click(); await new Promise(r => setTimeout(r, 500));"
                   "document.querySelector('[data-lookmine]').click();", 0.5)
        rows = await p.until(f"return {LOADED} && [...document.querySelectorAll('.mylist li')].map(l => l.textContent.replace(/\\s+/g, ' ').trim());", 8)
        r.check("a pack is one row in My designs, with what it brings and who wears it",
                rows and len(rows) == 1 and all(w in rows[0] for w in ("Pack check", "Vec check", "Tty check", "worn by 1 person")), rows)
        await p.js("document.querySelector('[data-rmdesign^=\"themes|uicheck-pack\"]').click();", 0.4)
        text = await p.js("return document.querySelector('#confirmLayer').textContent;")
        r.check("…removing it says what goes with it and who wears it", text and "Vec check" in text and "1 person" in text, text)
        await p.js("document.querySelector('#cYes').click();")
        gone = await p.until("return !!document.querySelector('#lookMine') && !document.querySelector('[data-rmdesign]') && "
                             "document.querySelectorAll('.mylist li').length === 0;", 12)
        left = sorted(n for k in ("themes", "backgrounds", "clocks") for n in os.listdir(os.path.join(r.designs_dir, k)) if n.startswith("uicheck-"))
        r.check("…one click removes all three", gone and left == [], left)
        st = await p.js("return [document.body.dataset.skin, document.body.dataset.bg, document.querySelector('[data-clock]').dataset.clockk];")
        logged = await p.js(API + "return (await q('GET', '/api/logs')).entries.filter(e => e.source.startsWith('client:')).map(e => e.msg);")
        r.check("…and whoever wore it gets the built-in look back, quietly", st == ["dusk", "scene", "digital"] and logged == [], [st, logged])
    finally:
        for kind, name in files:
            try:
                os.remove(os.path.join(r.designs_dir, kind, name))
            except OSError:
                pass


async def write_to_author(r):
    """Settings → About → Write to the author: the issue is shown, the QR code and the link follow it."""
    p = r.p
    open_about = ("document.querySelector('.top [data-go=settings]').click();"
                  "await new Promise(r => setTimeout(r, 500));"
                  "document.querySelector('[data-sp=about]').click();")
    await r.open()
    await p.js(open_about)
    await p.until("return !!document.querySelector('#writeAuthor');", 5)
    await p.js("document.querySelector('#writeAuthor').click();", 0.3)
    shown = await p.until("return !document.querySelector('#feedbackLayer').hidden && document.activeElement?.id === 'fbSubject' && "
                          "!!document.querySelector('#fbQr svg path');", 8)
    r.check("the dialog opens on the subject, with a QR code", shown)
    await p.js("const s = document.querySelector('#fbSubject'); s.value = 'Clock freezes'; s.dispatchEvent(new Event('input'));"
               "document.querySelector('#fbKind [data-v=idea]').click();", 0.2)
    body = await p.until("const b = document.querySelector('#fbBody').textContent; return b.startsWith('Idea: Clock freezes') && b;", 6)
    r.check("what will be sent follows the form", bool(body) and "PVE Homelab" in body and "Proxmox VE" in body, (body or "")[:120])
    r.check("an admin may add the error journal", await p.js("return !document.querySelector('#fbJournalRow').hidden;"))
    await p.js("document.querySelector('#fbJournal').click();")
    r.check("…which then shows in it", bool(await p.until("return document.querySelector('#fbBody').textContent.includes('Error journal');", 6)))
    await p.js("window.__opened = null; window.open = (u) => { window.__opened = u; return null; };"
               "document.querySelector('#fbOpen').click();", 0.3)
    url = await p.js("return window.__opened;")
    r.check("Open here opens the new issue on GitHub", bool(url) and url.startswith("https://github.com/gryniv/pve-homelab/issues/new?title=Idea%3A%20Clock%20freezes"),
            (url or "")[:100])
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    r.check("Esc closes it, focus back on the button, settings still open",
            await p.js("return document.querySelector('#feedbackLayer').hidden && document.activeElement?.id === 'writeAuthor' && "
                       "!document.querySelector('[data-layer=settings]').hidden;"))
    await r.open("guest@pve")
    await p.js(open_about)
    await p.until("return !!document.querySelector('#writeAuthor');", 5)
    await p.js("document.querySelector('#writeAuthor').click();", 0.3)
    await p.until("return !!document.querySelector('#fbQr svg path');", 8)
    r.check("someone without Sys.Audit can't add the journal", await p.js("return document.querySelector('#fbJournalRow').hidden;"))


async def node_updates(r):
    """The top bar's Proxmox updates: the button, its dialog, Check now, the setting, the widget's way in."""
    p = r.p
    await r.open(None)
    # the widget on the side column too, to see that both show one answer
    await p.js(API + "await q('POST', '/api/login', {user: 'ihor@pve', password: 'x'});"
               "const pr = (await q('GET', '/api/me')).prefs; pr.layout.side = ['updates'];"
               "await q('PUT', '/api/prefs', pr); await q('POST', '/api/logout');")
    await p.js("document.querySelector('[data-user=\"ihor@pve\"]').click();", 0.3)
    await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
    n = await p.until("const b = document.querySelector('#nodeUpd'); return !b.hidden && b.querySelector('.n').textContent;", 8)
    r.check("the top bar counts the packages waiting", n == "6", n)
    st = await p.js("const b = document.querySelector('#nodeUpd'); return [b.classList.contains('kern'), b.getAttribute('aria-label')];")
    r.check("…marks the new kernel among them and says so", st[0] and "6 Proxmox updates" in st[1] and "kernel" in st[1], st)
    await p.js("const b = document.querySelector('#nodeUpd'); b.focus(); b.click();", 0.4)
    d = await p.js("return [!document.querySelector('#nodeUpdLayer').hidden, document.querySelectorAll('#nodeUpdBody .pkglist li:not(.more)').length,"
                   " !!document.querySelector('#nodeUpdBody .nukern'), document.querySelector('#nodeUpdBody .nusum small')?.textContent,"
                   " document.activeElement?.id];")
    r.check("its dialog lists every package and the kernel note", d[:3] == [True, 6, True], d)
    r.check("…says when the lists were checked, focus on Close", "checked 5 h" in (d[3] or "") and d[4] == "nuClose", d)
    await p.js("document.querySelector('#nuCheck').click();", 0.1)
    busy = await p.js("const c = document.querySelector('#nuCheck'); return [c.disabled, c.textContent.trim()];")
    r.check("Check now waits for Proxmox", busy == [True, "Checking…"], busy)
    toast = await p.until("const t = document.querySelector('#toast'); return !t.hidden && t.textContent.startsWith('Checked') && t.textContent;", 8)
    r.check("…and tells what it found", toast == "Checked: 6 updates waiting", toast)
    after = await p.js("return [document.querySelector('#nuCheck').disabled, document.querySelector('#nodeUpdBody .nusum small').textContent,"
                       " document.querySelector('.w[data-w=updates] .sum span').textContent];")
    r.check("…the dialog and the widget both show the fresh check", after[0] is False and "checked 1 min" in after[1] and "checked 1 min" in after[2], after)
    await p.js("window.__rf = window.__rf || window.fetch; window.fetch = (u, o) => /node-updates\\/refresh/.test(String(u))"
               " ? Promise.resolve(new Response(JSON.stringify({error: 'Could not check for updates: exit code 100'}), {status: 502}))"
               " : window.__rf(u, o);"
               "document.querySelector('#nuCheck').click();")
    bad = await p.until("const t = document.querySelector('#toast'); return !t.hidden && t.classList.contains('bad') && t.textContent;", 6)
    r.check("a failed check says why and the button comes back", (bad or "").startswith("Could not check")
            and await p.js("return !document.querySelector('#nuCheck').disabled;"), bad)
    await p.js("window.fetch = window.__rf;")
    for key, code in (("Tab", 9), ("ArrowDown", 40)):
        await p.key(key, code)
        await asyncio.sleep(0.2)
        r.check(f"{key} keeps focus inside the dialog", await p.js("return !!document.activeElement?.closest('#nodeUpdLayer');"))
    await p.key("Escape", 27)
    await asyncio.sleep(0.3)
    st = await p.js("return [document.querySelector('#nodeUpdLayer').hidden, document.activeElement?.id];")
    r.check("Esc closes it and focus goes back to the button", st == [True, "nodeUpd"], st)
    await p.js("document.querySelector('.w[data-w=updates] [data-nu]').click();", 0.4)
    r.check("the widget's 'and N more' opens the same dialog", await p.js("return !document.querySelector('#nodeUpdLayer').hidden;"))
    await p.js("window.__opened = null; window.open = (u) => { window.__opened = u; return null; };"
               "document.querySelector('#nuOpen').click();", 0.3)
    st = await p.js("return [document.querySelector('#nodeUpdLayer').hidden, window.__opened];")
    r.check("Open Proxmox opens its web UI", st[0] and (st[1] or "").startswith("https://"), st)
    await p.js("document.querySelector('.top [data-go=settings]').click();"
               "await new Promise(r => setTimeout(r, 500)); document.querySelector('[data-sp=dash]').click();")
    have = await p.until("return !!document.querySelector('#pPveUpd');", 5)
    r.check("Settings → Dashboard has the top bar switch", bool(have))
    await p.js("document.querySelector('#pPveUpd').click();", 0.3)
    r.check("…turned off, the button goes", await p.js("return document.querySelector('#nodeUpd').hidden;"))
    await p.js("document.querySelector('#pPveUpd').click();", 0.3)
    r.check("…and back on, it returns", await p.js("return !document.querySelector('#nodeUpd').hidden;"))
    await r.open("guest@pve")
    await asyncio.sleep(4.5)   # the first check runs a few seconds after sign-in
    await p.js("document.querySelector('.top [data-go=settings]').click();"
               "await new Promise(r => setTimeout(r, 500)); document.querySelector('[data-sp=dash]').click();", 0.3)
    st = await p.js("return [document.querySelector('#nodeUpd').hidden, !!document.querySelector('#pPveUpd')];")
    r.check("someone who may not update the node sees neither", st == [True, False], st)


async def narrow(r):
    """Phones and tablets held upright: readable type, nothing wider than the screen, guests as cards."""
    p = r.p
    wide = ("const s = [...document.querySelectorAll('.A .scr')].find((e) => !e.hidden);"
            "const out = [...s.querySelectorAll('*')].filter((e) => { const b = e.getBoundingClientRect();"
            " return b.width && (b.right > innerWidth + 1 || b.left < -1) && !(e instanceof SVGElement) && !e.closest('.systems,.opentabs,.snav'); })"
            ".map((e) => (typeof e.className === 'string' && e.className) || e.tagName).slice(0, 5);"
            "return [document.documentElement.scrollWidth > innerWidth, s.scrollWidth > s.clientWidth, out];")
    try:
        for w, h in ((360, 740), (820, 1180)):
            await p.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=True)
            await r.open(None)
            st = await p.js(wide)
            r.check(f"{w}px: the sign-in screen fits the width", st == [False, False, []], st)
            order = await p.js("const y = (s) => document.querySelector(s).getBoundingClientRect().top;"
                               "return [y('[data-scr=login] .clock') < y('#loginForm'), y('#loginForm') < y('.zone-login')];")
            r.check(f"{w}px: the time, then signing in, then the widgets", order == [True, True], order)
            await r.open()
            await p.until("return !document.querySelector('#nodeUpd').hidden;", 6)   # the widest the top bar gets
            fs = await p.js("return parseFloat(getComputedStyle(document.querySelector('.A')).fontSize);")
            r.check(f"{w}px: the type is readable", fs >= 13, fs)
            st = await p.js(wide)
            r.check(f"{w}px: the dashboard fits the width, top bar included", st == [False, False, []], st)
            r.check(f"{w}px: sign-out is on screen", await p.js(
                "const b = document.querySelector('#logoutBtn').getBoundingClientRect(); return b.width > 0 && b.right <= innerWidth;"))
            await p.js("const s = document.querySelector('.scr-dash'); s.scrollTop = s.scrollHeight;", 0.3)
            r.check(f"{w}px: the side widgets can be scrolled to", await p.js(
                "const z = document.querySelector('.zone-side').getBoundingClientRect(); return z.height > 0 && z.top < innerHeight;"))
            await p.js("document.querySelector('[data-ptab=guests]').click();", 0.4)
            cards = await p.js("return getComputedStyle(document.querySelector('#guestrows tr')).display;")
            r.check(f"{w}px: guests are {'cards' if w < 640 else 'a table'}", cards == ("flex" if w < 640 else "table-row"), cards)
            await p.js("document.querySelector('#nodeUpd').click();", 0.5)
            st = await p.js("const b = document.querySelector('#nodeUpdLayer .confirm').getBoundingClientRect();"
                            "return [Math.round(b.left), Math.round(b.right), innerWidth];")
            r.check(f"{w}px: a dialog stays inside the screen", st[0] >= 0 and st[1] <= st[2], st)
            await p.key("Escape", 27)
            await p.js("document.querySelector('.me').click();", 0.6)
            st = await p.js(wide)
            r.check(f"{w}px: settings fit the width", st == [False, False, []], st)
    finally:
        await p.send("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1, mobile=False)


PARTS = {"saver": ["saver-time", "saver-weather"],
         "login": ["login-intro", "login-widgets", "login-form", "login-about", "login-power"],
         "dash": ["topbar", "brand", "open-tabs", "topbar-tools", "dash-body", "sidecol", "dash-main", "systems", "services"]}


async def layout_hooks(r):
    """The parts a theme may move (DESIGNS.md, "Moving things around") are all there, once each:
    renaming one breaks this check, not someone's design."""
    p = r.p
    count = "return Object.fromEntries(%s.map((n) => [n, document.querySelectorAll(`[data-scr=%s] [data-part=\"${n}\"]`).length]));"
    await r.open(None)
    for scr in ("login", "saver"):
        if scr == "saver":
            await p.js("document.querySelector('[data-part=login-power] [data-go=saver]').click();", 0.5)
        got = await p.js(count % (json.dumps(PARTS[scr]), scr))
        r.check(f"{scr}: every layout hook once", all(v == 1 for v in got.values()), got)
    await r.open()
    got = await p.js(count % (json.dumps(PARTS["dash"]), "dash"))
    r.check("dash: every layout hook once", all(v == 1 for v in got.values()), got)


TMUX = """/*
 * @kind theme
 * @name.en UI check tmux
 */
.A[data-skin="uicheck-tmux"],.A [data-skin="uicheck-tmux"]{--acc:#33ff77}
@media (min-width: 901px) {
  .A[data-skin="uicheck-tmux"] [data-part="topbar"]{position:absolute;left:0;right:0;bottom:0;border-top:1px solid var(--edge);border-bottom:0}
  .A[data-skin="uicheck-tmux"] [data-part="dash-body"]{top:0;bottom:3.6em}
  .A[data-skin="uicheck-tmux"] [data-scr="login"]{grid-template-columns:28em 1fr}
  .A[data-skin="uicheck-tmux"] [data-part="login-form"]{order:-1}
}
"""


async def layout_theme(r):
    """A theme that moves things around: the top bar at the bottom, the sign-in form on the left."""
    p = r.p
    if not r.designs_dir:
        print("  (skipped: needs --start-demo, which owns the designs folder)")
        return
    path = os.path.join(r.designs_dir, "themes", "uicheck-tmux.css")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TMUX)
    try:
        await r.open(None)
        await p.js(API + "await q('POST', '/api/login', {user: 'ihor@pve', password: 'x'});"
                   "const pr = (await q('GET', '/api/me')).prefs; pr.skin = 'uicheck-tmux';"
                   "await q('PUT', '/api/prefs', pr); await q('POST', '/api/logout');")
        await p.send("Page.navigate", url=r.base)
        await p.until("return !!document.querySelector('[data-user=\"ihor@pve\"]');", 15)
        await p.js("document.querySelector('[data-user=\"ihor@pve\"]').click();", 0.6)
        on = await p.until("return document.body.dataset.skin === 'uicheck-tmux';", 6)
        r.check("the sign-in screen takes the person's theme", bool(on))
        st = await p.js("const x = (s) => document.querySelector(s).getBoundingClientRect();"
                        "return [x('[data-part=login-form]').left < x('[data-part=login-intro]').left, document.documentElement.scrollWidth <= innerWidth];")
        r.check("…its sign-in form moved to the left, nothing wider than the screen", st == [True, True], st)
        await p.js("document.querySelector('#pw').value = 'x'; document.querySelector('#loginForm').requestSubmit();")
        await p.until("return document.querySelector('[data-scr=dash]')?.hidden === false && document.querySelectorAll('.sys .play').length > 0;", 15)
        await asyncio.sleep(0.6)
        st = await p.js("const x = (s) => document.querySelector(s).getBoundingClientRect(); const t = x('[data-part=topbar]'), b = x('[data-part=dash-body]');"
                        "return [Math.abs(t.bottom - innerHeight) < 2, b.bottom <= t.top + 1, b.top < 2, document.documentElement.scrollWidth <= innerWidth];")
        r.check("…the top bar sits at the bottom, the dashboard above it", st == [True, True, True, True], st)
        await p.js("document.querySelector('#logoutBtn').focus();")
        await p.key("ArrowUp", 38)
        await asyncio.sleep(0.2)
        up = await p.js("const a = document.activeElement; return !!a?.closest('[data-part=dash-body]') && a.id !== 'logoutBtn';")
        r.check("…and ArrowUp from it goes to what is now above it", up)
    finally:
        os.remove(path)


WHOLE = """/*
 * @kind theme
 * @name.en UI check whole
 * @background night
 * @clock flip
 * @option color = red | green
 * @option.en color Colour: red | green
 * @option.uk color Колір: червоний | зелений
 */
.A[data-skin="uicheck-whole"],.A [data-skin="uicheck-whole"]{--acc:#ff0000}
.A[data-skin="uicheck-whole"][data-o-color="green"],.A [data-skin="uicheck-whole"][data-o-color="green"]{--acc:#00ff00}
"""


async def update_check(r):
    """Settings → About → Check now: GitHub is asked at once, not hours later."""
    p = r.p
    open_about = ("document.querySelector('.top [data-go=settings]').click();"
                  "await new Promise(r => setTimeout(r, 500)); document.querySelector('[data-sp=about]').click();")
    await r.open()
    await p.js(open_about)
    r.check("an admin has Check now next to the version", bool(await p.until("return !!document.querySelector('#updCheck');", 5)))
    await p.js("document.querySelector('#toast').hidden = true; document.querySelector('#updCheck').click();")
    got = await p.until("const t = document.querySelector('#toast'); return !t.hidden && t.textContent;", 6)
    r.check("…and says this is the latest version", got == "This is the latest version", got)
    # a release appears meanwhile (the demo drops its held answer, as a real one would be out of date)
    await p.js(API + "await q('POST', '/api/demo/world', {update: true});", 0.2)
    await p.js("document.querySelector('#toast').hidden = true; document.querySelector('#updCheck').click();")
    got = await p.until("const t = document.querySelector('#toast'); return !t.hidden && t.textContent;", 6)
    pill = await p.js("return !document.querySelector('#updPill').hidden;")
    r.check("…and finds a new one without waiting hours, the top bar too", (got or "").startswith("A new PVE Homelab version") and pill, [got, pill])
    await r.open("guest@pve")
    await p.js(open_about, 0.6)
    r.check("someone without Sys.Modify has no Check now", await p.js("return !document.querySelector('#updCheck');"))
    r.check("…and no switch for automatic updates", await p.js("return !document.querySelector('#pAutoUpd');"))
    await r.open()
    await p.js(open_about, 0.6)
    was = await p.until("const c = document.querySelector('#pAutoUpd'); return c ? [c.checked] : null;", 6)
    await p.js("document.querySelector('#pAutoUpd').click();", 0.6)
    on = await p.until(API + "const u = await q('GET', '/api/update'); return u.auto === true && u.auto;", 4)
    await p.js("document.querySelector('[data-sp=look]').click(); await new Promise(r => setTimeout(r, 300)); document.querySelector('[data-sp=about]').click();", 0.5)
    kept = await p.js("return document.querySelector('#pAutoUpd').checked;")
    r.check("an admin switches automatic updates on in About, and it stays on", was == [False] and on is True and kept, [was, on, kept])
    await p.js(API + "await q('PUT', '/api/update/auto', {auto: false});")


async def theme_whole(r):
    """A theme as a whole: picking it brings its background and clock; its own setting changes the page."""
    p = r.p
    if not r.designs_dir:
        print("  (skipped: needs --start-demo, which owns the designs folder)")
        return
    path = os.path.join(r.designs_dir, "themes", "uicheck-whole.css")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(WHOLE)
    acc = "return getComputedStyle(document.body).getPropertyValue('--acc').trim();"
    try:
        await r.open()
        await p.js("document.querySelector('.top [data-go=settings]').click();", 0.6)
        await p.js("document.querySelector('[data-skinpick=\"uicheck-whole\"]').click();", 1.4)
        st = await p.js("return [document.body.dataset.skin, document.body.dataset.bg, document.querySelector('[data-clock]').dataset.clockk,"
                        " document.body.getAttribute('data-o-color')];")
        r.check("picking the theme brings its background and clock", st == ["uicheck-whole", "night", "flip", "red"], st)
        r.check("…its setting shows inside it, named in the person's language",
                await p.js("return document.querySelector('.topt')?.textContent.includes('Colour') && !!document.querySelector('#to-color [data-v=green]');"))
        r.check("…and the default value paints the page", await p.js(acc) == "#ff0000", await p.js(acc))
        await p.js("document.querySelector('#to-color [data-v=green]').click();", 0.8)
        st = await p.js("return [document.body.getAttribute('data-o-color'), getComputedStyle(document.body).getPropertyValue('--acc').trim()];")
        r.check("another value changes the page", st == ["green", "#00ff00"], st)
        mini = await p.js("const s = document.querySelector('[data-clk] .scrn'); return [s.getAttribute('data-o-color'), getComputedStyle(s).getPropertyValue('--acc').trim()];")
        r.check("…and the previews inside the design", mini == ["green", "#00ff00"], mini)
        saved = await p.until(API + "const o = (await q('GET', '/api/me')).prefs.theme_opts; return o['uicheck-whole']?.color;", 4)
        r.check("…and is kept", saved == "green", saved)
        await p.js("document.querySelector('#settingsBox .sclose, [data-go=dash]')?.click();", 0.3)
        await p.js("document.querySelector('#logoutBtn').click();", 1.2)
        await p.js("document.querySelector('[data-user=\"ihor@pve\"]').click();", 0.8)
        st = await p.js("return [document.body.dataset.skin, document.body.getAttribute('data-o-color')];")
        r.check("the sign-in screen shows the person's theme with their setting", st == ["uicheck-whole", "green"], st)
    finally:
        os.remove(path)


async def design_folders(r):
    """Settings → Look: designs are folders; inside one, its settings and what it is worn with, kept per design."""
    p = r.p
    await r.open()
    now = "return [document.body.dataset.skin, document.body.dataset.bg, document.querySelector('[data-clock]').dataset.clockk];"
    themes = await p.js(API + "return (await q('GET', '/api/public')).themes.map(t => t.id);")
    a = (await p.js(now))[0]
    worn_a = await p.js(now)
    b, c = [x for x in themes if x != a][:2]
    pick = lambda d: p.js(f"document.querySelector('[data-skinpick=\"{d}\"]').click();", 1.0)
    await p.js("document.querySelector('.top [data-go=settings]').click();", 0.6)
    grid = await p.js("return [document.querySelectorAll('[data-skinpick]').length, !!document.querySelector('[data-lookmine]'),"
                      " !!document.querySelector('#lookTabs'), document.querySelectorAll('[data-bgk], [data-clk]').length];")
    r.check("Look is one grid of designs and My designs, no tabs", grid == [len(themes), True, False, 0], grid)
    await pick(b)
    inside = await p.js("return [document.body.dataset.skin, !!document.querySelector('#lookBack'), !!document.querySelector('#lookReset'),"
                        " document.querySelectorAll('[data-bgk]').length > 3, document.querySelectorAll('[data-clk]').length > 1,"
                        " document.querySelectorAll('[data-font^=\"display|\"]').length > 1, document.querySelectorAll('[data-font^=\"ui|\"]').length > 1,"
                        " !!document.querySelector('[data-skinpick]'), document.activeElement?.id];")
    r.check("a design opens like a folder: it is worn, with its background, clock and fonts inside",
            inside == [b, True, True, True, True, True, True, False, "lookBack"], inside)
    r.check("…as it was designed, the first time", await p.js(now) == [b, "scene", "digital"], await p.js(now))
    await p.js("document.querySelector('[data-bgk=night]').click();", 0.4)
    await p.js("document.querySelector('[data-clk=flip]').click();", 0.6)
    await p.key("Escape", 27)
    await asyncio.sleep(0.4)
    st = await p.js("return [!document.querySelector('[data-layer=settings]')?.hidden, !!document.querySelector('[data-skinpick]'), !document.querySelector('#lookBack')];")
    r.check("Esc inside a design goes back to the grid, settings stay open", st == [True, True, True], st)
    await pick(c)
    r.check("another design comes as it was designed", await p.js(now) == [c, "scene", "digital"], await p.js(now))
    await p.js("document.querySelector('#lookBack').click();", 0.5)
    tile = await p.js(f"const s = document.querySelector('[data-skinpick=\"{b}\"] .scrn'); return [s.dataset.clockId, s.querySelector('.bgx')?.dataset.k];")
    r.check("…and the tile of the one before shows what it was worn with", tile == ["flip", "night"], tile)
    await pick(b)
    r.check("coming back to a design brings back what it was worn with", await p.js(now) == [b, "night", "flip"], await p.js(now))
    saved = await p.until(API + f"const l = (await q('GET', '/api/me')).prefs.looks; return l['{c}']?.background === 'scene' && l['{a}'] && l;", 4)
    r.check("…kept for each design", bool(saved), saved)
    await p.js("document.querySelector('#lookReset').click();", 0.8)
    r.check("As designed puts its own background and clock back", await p.js(now) == [b, "scene", "digital"], await p.js(now))
    await p.js("document.querySelector('#lookBack').click();", 0.5)
    await pick(a)
    r.check("the design worn before all this comes back as it was", await p.js(now) == worn_a, [await p.js(now), worn_a])
    await p.js("document.querySelector('#lookBack').click();", 0.5)
    await p.js("document.querySelector('[data-lookmine]').click();", 0.8)
    mine = await p.until(f"return !!document.querySelector('#lookMine') && !!document.querySelector('#designPick') && {LOADED};", 6)
    r.check("My designs is the last tile and opens the same way", mine)


async def widget_strings(r):
    """Every widget's strings come from its i18n/<lang>.json files, in each language."""
    p = r.p
    await r.open()
    raw = ("const W = await import('/core/widgets.js');"
           "return Object.values(W.all()).filter(w => !w.title || w.title === 'title' || w.title.startsWith('w.')).map(w => w.id);")
    count = await p.js("return Object.keys((await import('/core/widgets.js')).all()).length;")
    bad = await p.js(raw)
    r.check("every widget has its title in English", count and count >= 18 and bad == [], f"{count} widgets, untitled: {bad}")
    titles = await p.js("const I = await import('/core/i18n.js'); await I.setLang('uk');"
                        "const W = await import('/core/widgets.js'); const all = W.all();"
                        "const out = [all.note.title, all.weather.title, all.note.t('opt_text')]; await I.setLang('en'); return out;")
    r.check("…and in Ukrainian, options included", titles == ["Нотатка", "Погода", "Текст"], titles)


async def my_widgets(r):
    """A widget of your own: installed from Settings → Dashboard, put on the dashboard, removed."""
    p = r.p
    tmp = tempfile.mkdtemp(prefix="pvehomelab-uicheck-widget-")
    js, css, en = (os.path.join(tmp, n) for n in ("uicheck-w.js", "uicheck-w.css", "uicheck-w.en.json"))
    with open(js, "w", encoding="utf-8") as f:   # its strings come in a file of their own
        f.write("export default { zones: ['side'],\n"
                "  render: (_d, { ui, t }) => `<h4>${ui.esc(t('title'))}</h4><div class=\"uiw\">${ui.esc(t('hello'))}</div>` };\n")
    with open(en, "w", encoding="utf-8") as f:
        f.write('{"title": "UI check widget", "hello": "hello"}\n')
    with open(css, "w", encoding="utf-8") as f:
        f.write('.A .w[data-w="uicheck-w"] .uiw{color:rgb(1, 2, 3)}\n')
    open_dash = ("document.querySelector('.top [data-go=settings]').click();"
                 "await new Promise(r => setTimeout(r, 500));"
                 "document.querySelector('[data-sp=dash]').click();")
    in_dash = "!document.querySelector('[data-layer=settings]')?.hidden && document.querySelector('[data-sp=dash]')?.getAttribute('aria-selected') === 'true'"
    try:
        await r.open()
        await p.js(open_dash)
        r.check("an admin sees My widgets with an install button and the warning",
                await p.until(f"return !!document.querySelector('#widgetPick') && !!document.querySelector('.wwarn') && {LOADED};", 8))
        doc = await p.send("DOM.getDocument")
        node = await p.send("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#widgetFiles")
        await p.send("DOM.setFileInputFiles", files=[js, css, en], nodeId=node["nodeId"])
        back = await p.until(f"return {in_dash} && (document.querySelector('#myWidgets')?.textContent || '').includes('UI check widget');", 12)
        r.check("installing reloads back to Dashboard, listing the new widget", back)
        offered = await p.js("return [...document.querySelectorAll('#add-side option')].map(o => o.value);")
        r.check("…and it can be added to the dashboard", "uicheck-w" in (offered or []), offered)
        await p.js("const s = document.querySelector('#add-side'); s.value = 'uicheck-w'; s.dispatchEvent(new Event('change'));"
                   "document.querySelector('[data-add=side]').click();", 0.6)
        await p.js("document.querySelector('#sClose').click();", 0.6)
        shown = await p.until("const w = document.querySelector('[data-zone=side] [data-w=\"uicheck-w\"] .uiw');"
                              "return w && [w.textContent, getComputedStyle(w).color];", 8)
        r.check("it runs on the dashboard, in its own look", shown == ["hello", "rgb(1, 2, 3)"], shown)
        await p.js(open_dash)
        await p.until("return !!document.querySelector('[data-rmwidget^=\"uicheck-w|\"]');", 5)
        await p.js("document.querySelector('[data-rmwidget^=\"uicheck-w|\"]').click();", 0.4)
        await p.js("document.querySelector('#cYes').click();")
        gone = await p.until(f"return {in_dash} && !document.querySelector('#myWidgets') && !document.querySelector('[data-w=\"uicheck-w\"]');", 12)
        r.check("removing it reloads back, and it is gone from the list and the dashboard", gone)
        await r.open("guest@pve")
        await p.js(open_dash)
        guest = await p.until("return !document.querySelector('#widgetPick') && document.querySelector('.scont').textContent.includes('Installing widgets is for admins');", 5)
        r.check("someone without Sys.Modify is told installing widgets is for admins", guest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if r.widgets_dir:  # leave the demo as it was, whatever happened above
            shutil.rmtree(os.path.join(r.widgets_dir, "uicheck-w"), ignore_errors=True)
            try:
                os.remove(os.path.join(r.designs_dir, "widgets", "uicheck-w.css"))
            except OSError:
                pass


async def designing(r):
    """Live reload and the showcase, with real files in the demo's designs folder."""
    p = r.p
    if not r.designs_dir:
        r.check("designing (needs --start-demo: it writes into the demo's designs folder)", True)
        return
    theme = os.path.join(r.designs_dir, "themes", "uicheck-live.css")
    clock = os.path.join(r.designs_dir, "clocks", "uicheck-clock.js")
    os.makedirs(os.path.dirname(theme), exist_ok=True)
    os.makedirs(os.path.dirname(clock), exist_ok=True)

    def put(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    head = "/*\n * @kind theme\n * @name.en Live check\n */\n"
    put(theme, head + '.A[data-skin="uicheck-live"],.A [data-skin="uicheck-live"]{--acc:#00ff00}\n')
    put(clock, "/*\n * @kind clock\n * @name.en Live clock\n */\nexport const css = '';\nexport function render(el) { el.textContent = 'AAA'; }\n")
    try:
        await r.open()
        await p.send("Page.navigate", url=r.base + "&showcase=themes:uicheck-live")
        cells = await p.until("return document.querySelectorAll('#showcase .sccell .scrn').length;", 10)
        r.check("the showcase shows a design in every state", cells == 32, cells)
        acc = "return getComputedStyle(document.querySelector('#showcase .scrn[data-skin=\"uicheck-live\"]')).getPropertyValue('--acc').trim();"
        r.check("…in its colours", await p.until(acc + "", 5) == "#00ff00", await p.js(acc))
        await p.js("window.__stillHere = true;")
        put(theme, head + '.A[data-skin="uicheck-live"],.A [data-skin="uicheck-live"]{--acc:#ff00ff}\n')
        got = await p.until(acc.replace("return ", "const v = ").replace(";", "; return v === '#ff00ff' && v;"), 8)
        r.check("saving the file updates it in place", got == "#ff00ff", await p.js(acc))
        r.check("…without reloading the page", await p.js("return window.__stillHere === true;"))
        await p.key("Escape", 27)
        await asyncio.sleep(0.3)
        r.check("Esc closes the showcase", await p.js("return !document.querySelector('#showcase') && !location.search.includes('showcase');"))

        await p.send("Page.navigate", url=r.base + "&showcase=clocks:uicheck-clock")
        face = "return [...document.querySelectorAll('#showcase .ck')].map(c => c.textContent)[0];"
        r.check("a clock design shows in the showcase", await p.until(face, 10) == "AAA", await p.js(face))
        put(clock, "/*\n * @kind clock\n * @name.en Live clock\n */\nexport const css = '';\nexport function render(el) { el.textContent = 'BBB'; }\n")
        got = await p.until(face.replace("return ", "const v = ").replace(";", "; return v === 'BBB' && v;"), 8)
        r.check("a changed clock is drawn by its new code", got == "BBB", await p.js(face))
    finally:
        for f in (theme, clock):
            try:
                os.remove(f)
            except OSError:
                pass
        await asyncio.sleep(1.5)  # let live reload see the files go before the next check


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


CHECKS = {"guests": guests, "logout": logout, "tfa_signin": tfa_signin, "system_settings": system_settings, "components": components, "interface": interface, "guest_resources": guest_resources, "settings_copy": settings_copy, "away": away, "launch_input": launch_input, "input_settings": input_settings, "gamepad": gamepad, "widgets": widgets, "toasts": toasts, "offline": offline,
          "aria": dialogs_aria, "alerts": alerts, "update": failed_update, "focus": settings_focus,
          "console": console, "launch": launch, "search": search, "order": reorder, "guests_table": guest_table, "designs": my_designs, "design_pack": design_pack, "widget_strings": widget_strings, "my_widgets": my_widgets, "feedback": write_to_author, "node_updates": node_updates, "narrow": narrow, "layout_hooks": layout_hooks, "layout_theme": layout_theme, "theme_whole": theme_whole, "design_folders": design_folders, "update_check": update_check, "designing": designing, "quiet_faults": quiet_faults, "tabs": service_tabs, "misc": misc}


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
                if demo_state:
                    r.designs_dir = os.path.join(demo_state, "state", "designs")
                    r.widgets_dir = os.path.join(demo_state, "state", "widgets")
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
            try:
                demo.wait(10)
            except subprocess.TimeoutExpired:  # never let cleanup decide the result
                demo.kill()
                demo.wait(5)
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
