"""Screenshots of every screen at common monitor sizes, in a throwaway headless Chromium.

Run ON the host next to a dry-run backend (tools/dryrun.py):
    python3 tools/screenshots.py --out /tmp/shots [--sizes 1920x1080,2560x1440] [--lang en]
Also prints layout problems it can measure: horizontal overflow and clipped text.
"""

import argparse
import asyncio
import base64
import json
import os
import subprocess

import aiohttp

SIZES = ["1280x720", "1366x768", "1920x1080", "2560x1440", "3840x2160",
         "1280x1024", "1024x768", "1920x1200", "3440x1440", "2560x1080"]

# Elements whose content must fit: returns a list of offenders.
CHECK = r"""
(() => {
  const bad = [];
  const vis = (e) => e.getClientRects().length && !e.closest('[hidden]');
  if (document.documentElement.scrollWidth > innerWidth + 1) bad.push('page scrolls horizontally');
  for (const e of document.querySelectorAll('.A *')) {
    if (!vis(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width > 4 && (r.right > innerWidth + 2 || r.left < -2) && !e.closest('.land,#fx,.opentabs,.cloud'))
      bad.push('off-screen x: ' + (e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right));
    if (r.height > 4 && r.bottom > innerHeight + 2 && !e.closest('.scroll,.zone-side,.scont,.land,#fx'))
      bad.push('off-screen y: ' + (e.className || e.tagName) + ' bottom ' + Math.round(r.bottom));
  }
  for (const e of document.querySelectorAll('.A h3, .A h5, .A .clock, .A button, .A .n, .A .nm')) {
    if (!vis(e)) continue;
    const cs = getComputedStyle(e);
    if (cs.textOverflow !== 'ellipsis' && e.scrollWidth > e.clientWidth + 2 && cs.overflow !== 'visible')
      bad.push('clipped text: ' + (e.className || e.tagName) + ' "' + e.textContent.trim().slice(0, 24) + '"');
  }
  return [...new Set(bad)].slice(0, 12);
})()
"""


async def run(out, base, sizes, lang):
    os.makedirs(out, exist_ok=True)
    proc = subprocess.Popen(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                             "--remote-debugging-port=9333", "--user-data-dir=/tmp/pve-seat-shots-prof", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {}
    try:
        for _ in range(50):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get("http://127.0.0.1:9333/json") as r:
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

            async def js(expr):
                r = await cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value")

            async def shot(name):
                r = await cmd("Page.captureScreenshot", format="jpeg", quality=80)
                with open(os.path.join(out, name + ".jpg"), "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                report[name] = await js(CHECK)

            await cmd("Page.navigate", url=base)
            await asyncio.sleep(3)
            await js("document.querySelector('#pw').value='test';document.querySelector('#loginForm').requestSubmit()")
            await asyncio.sleep(8)
            if lang:
                await js(f"fetch('/api/prefs?seat=igpu',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(Object.assign({{}},window.__prefs||{{}},{{lang:'{lang}'}}))}})")
            for size in sizes:
                w, h = map(int, size.split("x"))
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
                await cmd("Page.navigate", url=base)
                await asyncio.sleep(4)
                await shot(f"{size}-1-dash")
                await js("document.querySelector('[data-ptab=guests]').click()")
                await asyncio.sleep(0.6)
                await shot(f"{size}-2-guests")
                await js("document.querySelector('[data-ptab=web]').click();document.querySelector('[data-sys]')?.click()")
                await asyncio.sleep(0.9)
                await shot(f"{size}-3-launch")
                await js("document.querySelector('#mCancel').click();document.querySelector('.top [data-go=settings]').click()")
                await asyncio.sleep(0.8)
                await shot(f"{size}-4-settings")
                await js("document.querySelector('#sClose').click();document.querySelector('#logoutBtn').click()")
                await asyncio.sleep(2)
                await shot(f"{size}-5-login")
                await js("document.querySelector('#pw').value='test';document.querySelector('#loginForm').requestSubmit()")
                await asyncio.sleep(5)
    finally:
        proc.kill()
    for name, issues in report.items():
        print(("OK   " if not issues else "WARN ") + name + ("" if not issues else "\n       " + "\n       ".join(issues)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/pve-seat-shots")
    ap.add_argument("--url", default="http://127.0.0.1:8901/?seat=igpu")
    ap.add_argument("--sizes", default=",".join(SIZES))
    ap.add_argument("--lang", default="")
    a = ap.parse_args()
    asyncio.run(run(a.out, a.url, a.sizes.split(","), a.lang))


if __name__ == "__main__":
    main()
