import asyncio
import glob
import os
import re
import secrets
import socket
import time
from urllib.parse import quote

import aiohttp
from aiohttp import web

from . import caddy, config, gpus as G, icons, prefs, weather
from .ddc import DDC
from .host import HostStats
from .launch import Launcher
from .pve import PVE, PVEError
from .util import Cached, log, pvesh

COOKIE = "pveseat_sid"
routes = web.RouteTableDef()


# ---------------- helpers ----------------
def err(status, msg):
    return web.json_response({"error": msg}, status=status)


def seat_of(req):
    seat = req.query.get("seat") or req.headers.get("X-Seat") or ""
    if seat not in req.app["cfg"]["seats"]:
        raise web.HTTPBadRequest(text="unknown seat")
    return seat


async def session(req):
    sid = req.cookies.get(COOKIE)
    s = req.app["sessions"].get(sid)
    if not s:
        raise web.HTTPUnauthorized(text="login required")
    s["seen"] = time.time()
    await req.app["pve"].renew(s["ticket"])
    return s


@web.middleware
async def errors(req, handler):
    try:
        return await handler(req)
    except PVEError as e:
        return err(e.status, str(e))
    except web.HTTPException as e:
        if req.path.startswith("/api/") and e.status >= 400:
            return err(e.status, e.text or e.reason)
        raise
    except Exception as e:
        log.exception("%s %s", req.method, req.path)
        return err(500, str(e))


def pve_users(app):
    users = []
    try:
        with open("/etc/pve/user.cfg", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("user:"):
                    continue
                p = line.strip().split(":")
                uid, enable, first, last = p[1], p[2], p[4], p[5]
                if enable == "0" or uid in app["cfg"]["users"]["hide"]:
                    continue
                pr = prefs.load(uid)
                if not pr["show_on_login"]:
                    continue
                name = first or uid.split("@")[0]
                users.append({"id": uid, "name": name, "full": " ".join(x for x in (first, last) if x),
                              "avatar": pr["avatar"], "skin": pr["skin"], "background": pr["background"],
                              "login": pr["layout"].get("login", [])})
    except OSError:
        pass
    return users


def list_dir_modules(sub, pattern):
    base = os.path.join(config.WEB_DIR, sub)
    return sorted(os.path.basename(os.path.dirname(p)) if pattern.endswith("widget.js") else p
                  for p in glob.glob(os.path.join(base, pattern)))


def themes():
    out = []
    for path in sorted(glob.glob(os.path.join(config.WEB_DIR, "themes", "*.css"))):
        with open(path, encoding="utf-8") as f:
            head = f.read(600)
        meta = dict(re.findall(r"@(\w+)\s+([^\n*]+)", head))
        tid = os.path.splitext(os.path.basename(path))[0]
        out.append({"id": tid, "name": meta.get("name", tid).strip(), "desc": meta.get("desc", "").strip(),
                    "preview": meta.get("preview", "").strip(), "accent": meta.get("accent", "").strip()})
    return out


# ---------------- public (before login) ----------------
@routes.get("/api/public")
async def public(req):
    app, cfg = req.app, req.app["cfg"]
    seat = seat_of(req)
    res = await app["resources"].get()
    guests = [g for g in res if not g.get("template")]
    return web.json_response({
        "node": cfg["node"],
        "version": app["pveversion"],
        "ip": app["host_ip"],
        "seat": {"id": seat, **cfg["seats"][seat], "gpu_name": await G.pretty_name(cfg["seats"][seat]["gpu"])},
        "host": app["stats"].snapshot(),
        "guests": {"running": sum(g.get("status") == "running" for g in guests),
                   "stopped": sum(g.get("status") != "running" for g in guests)},
        "users": pve_users(app),
        "weather": cfg["weather"],
        "saver_after_min": cfg["saver"]["after_min"],
        "lock_after_min": cfg["lock_after_min"],
        "themes": themes(),
        "widgets": list_dir_modules("widgets", "*/widget.js"),
    })


@routes.get("/api/weather")
async def get_weather(req):
    cfg = req.app["cfg"]["weather"]
    city = req.query.get("city") or cfg["city"]
    units = req.query.get("units") or cfg["units"]
    try:
        return web.json_response(await weather.get(city, units))
    except ValueError as e:
        return err(404, str(e))


@routes.get("/api/host")
async def host(req):
    return web.json_response(req.app["stats"].snapshot())


@routes.get("/icons/{slug}.svg")
async def icon(req):
    data = await icons.get(req.match_info["slug"])
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


# ---------------- session ----------------
@routes.post("/api/login")
async def login(req):
    body = await req.json()
    seat = seat_of(req)
    t = await req.app["pve"].login(body.get("user", ""), body.get("password", ""))
    sid = secrets.token_urlsafe(32)
    req.app["sessions"][sid] = {"ticket": t, "seat": seat, "user": t.user, "seen": time.time()}
    resp = web.json_response({"user": t.user, "prefs": prefs.load(t.user)})
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="Strict", path="/")
    log.info("login %s on seat %s", t.user, seat)
    return resp


@routes.post("/api/logout")
async def logout(req):
    req.app["sessions"].pop(req.cookies.get(COOKIE), None)
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE, path="/")
    return resp


@routes.get("/api/me")
async def me(req):
    s = await session(req)
    return web.json_response({"user": s["user"], "prefs": prefs.load(s["user"])})


@routes.put("/api/prefs")
async def put_prefs(req):
    s = await session(req)
    return web.json_response(prefs.save(s["user"], await req.json()))


# ---------------- data for logged-in users ----------------
@routes.get("/api/guests")
async def guests(req):
    s = await session(req)
    res = await req.app["pve"].get(s["ticket"], "/cluster/resources", type="vm")
    keep = ("type", "vmid", "name", "status", "cpu", "maxcpu", "mem", "maxmem", "uptime", "tags", "template")
    return web.json_response(sorted(({k: g.get(k) for k in keep} for g in res or [] if not g.get("template")),
                                    key=lambda g: (g["type"] != "qemu", g["vmid"])))


@routes.post("/api/guests/{type}/{vmid}/{action}")
async def guest_action(req):
    s = await session(req)
    typ, vmid, action = req.match_info["type"], int(req.match_info["vmid"]), req.match_info["action"]
    if typ not in ("qemu", "lxc") or action not in ("start", "shutdown", "stop", "reboot"):
        raise web.HTTPBadRequest(text="bad action")
    node = req.app["cfg"]["node"]
    upid = await req.app["pve"].post(s["ticket"], f"/nodes/{node}/{typ}/{vmid}/status/{action}")
    req.app["resources"].invalidate()
    return web.json_response({"upid": upid})


@routes.get("/api/services")
async def services(req):
    s = await session(req)
    data = await req.app["services"].get()
    visible = {(g["type"], g["vmid"]): g for g in await req.app["pve"].get(s["ticket"], "/cluster/resources", type="vm") or []}
    out = []
    for svc in data:
        g = svc["guest"]
        st = None
        if g and g["type"] == "node":
            st = "running"
        elif g and (g["type"], g["vmid"]) in visible:
            st = visible[(g["type"], g["vmid"])].get("status")
        out.append({**svc, "status": st})
    return web.json_response(out)


@routes.get("/api/storage")
async def storage(req):
    s = await session(req)
    node = req.app["cfg"]["node"]
    res = await req.app["pve"].get(s["ticket"], f"/nodes/{node}/storage")
    return web.json_response([{"id": r["storage"], "type": r.get("type"), "used": r.get("used", 0),
                               "total": r.get("total", 0)} for r in res or [] if r.get("active") and r.get("total")])


@routes.get("/api/gpus")
async def gpus(req):
    await session(req)
    running = await req.app["running"]()
    return web.json_response(await G.list_gpus(running))


@routes.get("/api/systems")
async def systems(req):
    s = await session(req)
    seat = seat_of(req)
    L = req.app["launcher"]
    out = []
    for vm in await L.systems(s["ticket"]):
        out.append({**vm, "options": await L.options(seat, vm)})
    return web.json_response(out)


@routes.post("/api/launch")
async def launch(req):
    s = await session(req)
    body = await req.json()
    job = await req.app["launcher"].launch(s["ticket"], seat_of(req), int(body["vmid"]), body["gpu"])
    req.app["resources"].invalidate()
    return web.json_response(job.as_dict())


@routes.get("/api/jobs/{id}")
async def job(req):
    await session(req)
    j = req.app["launcher"].jobs.get(int(req.match_info["id"]))
    if not j:
        raise web.HTTPNotFound()
    return web.json_response(j.as_dict())


@routes.post("/api/console/{vmid}")
async def console_open(req):
    """VNC ticket for a VM's screen, issued with the user's own PVE ticket."""
    s = await session(req)
    vmid = int(req.match_info["vmid"])
    node = req.app["cfg"]["node"]
    d = await req.app["pve"].post(s["ticket"], f"/nodes/{node}/qemu/{vmid}/vncproxy", websocket=1)
    token = secrets.token_urlsafe(24)
    req.app["consoles"][token] = {"ticket": s["ticket"], "vmid": vmid, "port": d["port"],
                                  "vncticket": d["ticket"], "at": time.time()}
    return web.json_response({"token": token, "password": d["ticket"]})


@routes.get("/api/console/ws/{token}")
async def console_ws(req):
    """Relay the browser's noVNC websocket to PVE's vncwebsocket."""
    c = req.app["consoles"].pop(req.match_info["token"], None)
    if not c or time.time() - c["at"] > 60:
        raise web.HTTPForbidden(text="console token expired")
    node = req.app["cfg"]["node"]
    url = (f"wss://127.0.0.1:8006/api2/json/nodes/{node}/qemu/{c['vmid']}/vncwebsocket"
           f"?port={c['port']}&vncticket={quote(c['vncticket'], safe='')}")
    http = await req.app["pve"].http()
    up = await http.ws_connect(url, protocols=("binary",), max_msg_size=0,
                               headers={"Cookie": f"PVEAuthCookie={quote(c['ticket'].ticket, safe='')}"})
    down = web.WebSocketResponse(protocols=("binary",), max_msg_size=0)
    await down.prepare(req)

    async def pump(src, dst):
        async for msg in src:
            if msg.type == aiohttp.WSMsgType.BINARY:
                await dst.send_bytes(msg.data)
            elif msg.type == aiohttp.WSMsgType.TEXT:
                await dst.send_str(msg.data)
            else:
                break
        await dst.close()

    await asyncio.gather(pump(up, down), pump(down, up), return_exceptions=True)
    await up.close()
    return down


@routes.post("/api/host/power")
async def host_power(req):
    s = await session(req)
    cmd = (await req.json()).get("cmd")
    if cmd not in ("reboot", "shutdown"):
        raise web.HTTPBadRequest(text="bad command")
    await req.app["pve"].post(s["ticket"], f"/nodes/{req.app['cfg']['node']}/status", command=cmd)
    return web.json_response({"ok": True})


# ---------------- static ----------------
@routes.get("/")
async def index(req):
    return web.FileResponse(os.path.join(config.WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


# ---------------- app ----------------
async def on_startup(app):
    cfg = app["cfg"]
    app["pve"] = PVE()
    app["stats"] = HostStats()
    app["ddc"] = DDC(cfg["monitors"])
    app["sessions"] = {}
    app["consoles"] = {}
    app["host_ip"] = _host_ip()
    try:
        app["pveversion"] = (await pvesh("/version"))["version"]
    except Exception:
        app["pveversion"] = ""

    async def resources():
        return await pvesh("/cluster/resources", type="vm") or []
    app["resources"] = Cached(resources, 10)

    async def running(fresh=False):
        if fresh:
            app["resources"].invalidate()
        return {g["vmid"] for g in await app["resources"].get() if g.get("status") == "running"}
    app["running"] = running

    async def build_services():
        res = await app["resources"].get()
        ips = await caddy.guest_ips(cfg["node"], res)
        return caddy.build(cfg, await caddy.routes(cfg), ips, app["host_ip"])
    app["services"] = Cached(build_services, 60, stale=True)

    app["launcher"] = Launcher(app)
    app["tasks"] = [asyncio.create_task(app["stats"].loop()),
                    asyncio.create_task(app["launcher"].watch_loop()),
                    asyncio.create_task(app["services"].get())]
    await _adopt_running(app)


async def _adopt_running(app):
    """Watch VMs that already hold a GPU wired to a menu monitor (started before us)."""
    cfg, ddc = app["cfg"], app["ddc"]
    try:
        running = await app["running"]()
        for g in await G.list_gpus(running):
            vm, mon = g["running_vm"], ddc.monitor_for_gpu(g["pci"])
            if not vm or not mon:
                continue
            seat_gpu = next((s["gpu"] for s in cfg["seats"].values()
                             if s.get("kiosk") and ddc.monitor_for_gpu(s["gpu"]) == mon), None)
            if seat_gpu:
                app["launcher"].watch[vm] = (mon, seat_gpu)
                log.info("watching VM %s on monitor %s", vm, mon)
    except Exception as e:
        log.warning("adopt running VMs: %s", e)


async def on_cleanup(app):
    for t in app.get("tasks", []):
        t.cancel()
    await app["pve"].close()


def _host_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


async def _no_stale_code(req, resp):
    # After an update the kiosk must pick up new JS/CSS without a manual cache flush.
    if req.path.endswith((".js", ".css", ".html")) or req.path == "/":
        resp.headers["Cache-Control"] = "no-cache"


def make_app():
    app = web.Application(middlewares=[errors])
    app.on_response_prepare.append(_no_stale_code)
    app["cfg"] = config.load()
    app.add_routes(routes)
    app.router.add_static("/", config.WEB_DIR, show_index=False, append_version=False)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
