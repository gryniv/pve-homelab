"""Screenshots for the README, taken from the demo in a headless Chrome/Chromium.

    python demo.py --no-browser &                 # the demo on :8900
    python tools/readme_shots.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"

Signs in as the demo user, sets an English, predictable look, walks through the screens and
writes docs/screenshots/*.jpg. The demo user's settings are put back afterwards.
"""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import tempfile

import aiohttp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def run(browser, base, out, w, h):
    os.makedirs(out, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="pvehomelab-shots-")
    proc = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio",
                             "--remote-debugging-port=9334", f"--user-data-dir={prof}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(60):
            try:
                async with aiohttp.ClientSession() as s, s.get("http://127.0.0.1:9334/json") as r:
                    page = next(t for t in await r.json() if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.3)
        async with aiohttp.ClientSession() as s, s.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            n = 0

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send_json({"id": n, "method": method, "params": params})
                async for m in ws:
                    d = json.loads(m.data)
                    if d.get("id") == n:
                        return d.get("result", {})

            async def js(expr, wait=0.0):
                r = await cmd("Runtime.evaluate", expression=f"(async () => {{ {expr} }})()", awaitPromise=True, returnByValue=True)
                if wait:
                    await asyncio.sleep(wait)
                return r.get("result", {}).get("value")

            async def shot(name):
                r = await cmd("Page.captureScreenshot", format="jpeg", quality=84)
                with open(os.path.join(out, name + ".jpg"), "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                print("  ", name)

            async def hover(sel):
                box = await js(f"const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 3];")
                await cmd("Input.dispatchMouseEvent", type="mouseMoved", x=box[0], y=box[1])

            api = "const q = (m, p, b) => fetch(p + (p.includes('?') ? '&' : '?') + 'seat=igpu', {method: m, headers: {'Content-Type': 'application/json', 'X-Seat': 'igpu'}, body: b && JSON.stringify(b)}).then((r) => r.json());"
            login = "document.querySelector('#pw').value = 'demo'; document.querySelector('#loginForm').requestSubmit();"
            # the demo's own ribbon and hint toasts are not part of the product
            clean = "document.head.insertAdjacentHTML('beforeend', '<style>.demo-ribbon,#toast{display:none!important}.A.demo .top{padding-left:0!important}</style>');"

            async def go(wait):
                await cmd("Page.navigate", url=base)
                await asyncio.sleep(2)
                await js(clean, wait)

            await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
            await go(2)
            await js(login, 4)
            saved = await js(api + "return (await q('GET', '/api/me')).prefs;")
            look = {"lang": "en", "skin": "dusk", "background": "scene", "clock": "digital", "fonts": {"ui": "", "display": ""},
                    "sky_by_time": False, "weather_react": True,
                    "layout": {"login": ["weather", "host"], "side": ["host", "gpus", "worldclock"]}}

            async def use(**over):
                await js(api + f"await q('PUT', '/api/prefs', Object.assign({json.dumps(saved)}, {json.dumps({**look, **over})}));")

            await use()
            await js(api + "await q('POST', '/api/demo/world', {weather: 'partly', update: false});")

            # dashboard, guests, launch
            await go(4)
            await shot("dashboard")
            await js("document.querySelector('[data-ptab=guests]').click();", 1)
            await shot("guests")
            await js("document.querySelector('[data-ptab=web]').click(); document.querySelector('[data-sys]').click();", 1.2)
            await shot("launch")
            # settings
            await js("document.querySelector('#mCancel').click(); document.querySelector('.top [data-go=settings]').click();", 1.2)
            await shot("settings-theme")
            await js("document.querySelector('#lookTabs [data-v=bg]').click();", 1.5)
            await hover("[data-bgk=mountains]")
            await asyncio.sleep(2.6)
            await shot("settings-backgrounds")
            await js("document.querySelector('#lookTabs [data-v=clock]').click();", 1.5)
            await shot("settings-clock")
            await js("document.querySelector('[data-sp=dash]').click();", 0.8)
            await js("document.querySelector('[data-wcfg=\"side|worldclock\"]').click();", 1.5)
            await js("document.querySelector('.wcfg').scrollIntoView({block: 'center'});", 0.5)
            await shot("settings-widgets")
            await js("document.querySelector('[data-sp=login]').click();", 1.5)
            await shot("settings-login")
            await js("document.querySelector('[data-sp=weather]').click();", 0.6)
            await js("document.querySelector('#showSaver').click();", 3)
            await shot("screensaver")

            # the sign-in screen in a few looks (backgrounds are chosen per user)
            # (the weather goes through the demo's fake forecast, so rain and snow really fall)
            gallery = [("login", {}, "dusk", "partly"),
                       ("look-mountains", {"background": "mountains", "skin": "dusk"}, "day", "clear"),
                       ("look-city", {"background": "city", "skin": "ice", "clock": "flip"}, "night", "clear"),
                       ("look-sea", {"background": "sea", "skin": "forest", "clock": "thin"}, "dawn", "partly"),
                       ("look-rain", {"background": "hills", "skin": "graphite", "clock": "analog"}, "day", "rain"),
                       ("look-snow", {"background": "night", "skin": "ice", "clock": "neon"}, "night", "snow")]
            for name, over, tod, wx in gallery:
                await use(**over)
                await js(api + f"await q('POST', '/api/demo/world', {{weather: '{wx}'}});")
                await go(1.5)
                await js("document.querySelector('#logoutBtn').click();", 3)
                await js(f"document.body.dataset.tod = '{tod}';", 2.5)
                await shot(name)
                await js(login, 3)

            await js(api + f"await q('PUT', '/api/prefs', {json.dumps(saved)}); await q('POST', '/api/demo/world', {{weather: '', update: true}});")
    finally:
        proc.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="chromium")
    ap.add_argument("--url", default="http://127.0.0.1:8900/?seat=igpu")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "screenshots"))
    ap.add_argument("--size", default="1600x900")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    asyncio.run(run(a.browser, a.url, a.out, w, h))


if __name__ == "__main__":
    main()
