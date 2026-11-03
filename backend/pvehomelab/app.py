import asyncio
import glob
import json
import os
import re
import secrets
import socket
import time
from urllib.parse import quote

import aiohttp
from aiohttp import web

from . import caddy, config, discover, errlog, gpus as G, i18n, icons, prefs, update, weather, wol
from .ddc import DDC
from .host import HostStats
from .launch import Launcher
from .pve import PVE, PVEError
from .util import Cached, log, pvesh, run

COOKIE = "pvehomelab_sid"
routes = web.RouteTableDef()


# ---------------- helpers ----------------
def err(status, msg):
    return web.json_response({"error": msg}, status=status)


def vmid_of(value):
    """A VM/CT id from the URL or a request body; anything else is the caller's mistake (400)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="bad vmid")
    if not 100 <= v <= 999999999:
        raise web.HTTPBadRequest(text="bad vmid")
    return v


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


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _hostname(value):
    """Host part of a Host header or an Origin URL, without port and brackets."""
    v = value.split("://", 1)[-1].split("/", 1)[0]
    if v.startswith("["):
        return v[1:].split("]", 1)[0].lower()
    return v.rsplit(":", 1)[0].lower() if v.count(":") == 1 else v.lower()


def allowed_hosts(app):
    cfg = app["cfg"]
    hosts = set(LOOPBACK) | {h.lower() for h in cfg.get("allowed_hosts") or []}
    listen = _hostname(cfg["listen"])
    if listen not in LOOPBACK:
        hosts |= {listen, app.get("host_ip", ""), socket.gethostname().lower()}
    return hosts


@web.middleware
async def guard(req, handler):
    """The menu is meant for this machine. A web page elsewhere must not reach it through a
    rebound DNS name (wrong Host), nor post to it from its own origin (wrong Origin)."""
    hosts = req.app.get("allowed_hosts_cache") or allowed_hosts(req.app)
    if "*" not in hosts:
        if _hostname(req.headers.get("Host", "")) not in hosts:
            return err(421, "unknown host")
        origin = req.headers.get("Origin")
        if req.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != "null" \
                and _hostname(origin) not in hosts:
            return err(403, "cross-origin request refused")
    return await handler(req)


@web.middleware
async def errors(req, handler):
    i18n.lang.set(i18n.pick(req.headers.get("X-Lang")) or req.app["cfg"]["language"])
    try:
        return await handler(req)
    except PVEError as e:
        # 4xx from Proxmox is the user's business (wrong password, no permission); 5xx is ours
        if e.status >= 500:
            log.warning("PVE %s on %s %s: %s", e.status, req.method, req.path, e)
        return err(e.status, str(e))
    except web.HTTPException as e:
        if e.status >= 500:
            log.warning("%s %s -> %s %s", req.method, req.path, e.status, e.text or e.reason)
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
                # One user's unreadable settings must not take the sign-in screen down for everyone.
                try:
                    pr = prefs.load(uid)
                    pub = prefs.public(pr)
                except Exception as e:
                    log.warning("settings of %s unreadable, using defaults: %s", uid, e)
                    pr = prefs.load_defaults()
                    pub = prefs.public(pr)
                if not pr["show_on_login"]:
                    continue
                name = first or uid.split("@")[0]
                users.append({"id": uid, "name": name, "full": " ".join(x for x in (first, last) if x), **pub})
    except OSError:
        pass
    return users


def list_dir_modules(sub, pattern):
    base = os.path.join(config.WEB_DIR, sub)
    return sorted(os.path.basename(os.path.dirname(p)) if pattern.endswith("widget.js") else p
                  for p in glob.glob(os.path.join(base, pattern)))


def catalog(sub, ext):
    """Drop-in modules: every web/<sub>/<id>.<ext> is one item. Its metadata lives in the
    header comment: @name.uk Сутінки / @name.en Dusk / @desc.uk … / @group … / @order 10 …
    (themes, backgrounds, clocks, fonts all work this way, so adding one is adding a file)."""
    out = []
    for path in glob.glob(os.path.join(config.WEB_DIR, sub, "*." + ext)):
        with open(path, encoding="utf-8") as f:
            m = re.search(r"/\*(.*?)\*/", f.read(4000), re.S)
        mid = os.path.splitext(os.path.basename(path))[0]
        meta = {"id": mid, "name": {}, "desc": {}}
        for key, code, val in re.findall(r"@(\w+)(?:\.(\w+))?[ \t]+([^\n*]+)", m.group(1) if m else ""):
            if key in ("name", "desc"):
                meta[key][code or "en"] = val.strip()
            else:
                meta[key] = val.strip()
        meta["name"] = meta["name"] or {"en": mid}
        out.append(meta)
    return sorted(out, key=lambda m: (int(m.get("order", 50)), m["id"]))


def themes():
    return catalog("themes", "css")


def languages():
    """Every web/i18n/<code>.json is a language; its "_name" is shown in the picker."""
    out = []
    for path in sorted(glob.glob(os.path.join(config.WEB_DIR, "i18n", "*.json"))):
        code = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                name = json.load(f).get("_name", code)
        except (OSError, ValueError):
            continue
        out.append({"code": code, "name": name})
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
        "demo": app.get("demo", False),
        "app": {"version": update.installed()["version"], "repo": update.settings(cfg)["repo"]},
        "version": app["pveversion"],
        "ip": app["host_ip"],
        "seat": {"id": seat, **cfg["seats"][seat], "gpu_name": await G.pretty_name(cfg["seats"][seat]["gpu"])},
        "host": app["stats"].snapshot(),
        "guests": {"running": sum(g.get("status") == "running" for g in guests),
                   "stopped": sum(g.get("status") != "running" for g in guests)},
        "users": pve_users(app),
        "language": cfg["language"],
        "languages": languages(),
        "systems_tag": cfg["systems_tag"],
        "weather": cfg["weather"],
        "saver_after_min": cfg["saver"]["after_min"],
        "lock_after_min": cfg["lock_after_min"],
        "themes": themes(),
        "backgrounds": catalog("backgrounds", "css"),
        "clocks": catalog("clocks", "js"),
        "fonts": catalog("fonts", "css"),
        "login": prefs.load_login(),
        "widgets": list_dir_modules("widgets", "*/widget.js"),
    })


@routes.get("/api/weather")
async def get_weather(req):
    cfg = req.app["cfg"]["weather"]
    city = (req.query.get("city") or cfg["city"])[:100]
    units = req.query.get("units") or cfg["units"]
    if units not in ("c", "f"):
        units = "c"
    try:
        return web.json_response(await weather.get(city, units))
    except ValueError as e:
        return err(404, str(e))


@routes.get("/api/health")
async def health(req):
    """Alive, and with which code: the commit this process started with (not what is on disk now).
    The updater waits for this to report the version it just installed."""
    return web.json_response({"ok": True, **req.app["code"]})


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
LOGIN_TRIES, LOGIN_WINDOW = 5, 60  # wrong passwords per user name per minute


@routes.post("/api/login")
async def login(req):
    body = await req.json()
    seat = seat_of(req)
    user = str(body.get("user", ""))
    fails = req.app["login_fails"]
    now = time.time()
    recent = [x for x in fails.get(user.lower(), []) if now - x < LOGIN_WINDOW]
    if len(recent) >= LOGIN_TRIES:
        raise web.HTTPTooManyRequests(text=i18n._("too_many_logins", s=int(LOGIN_WINDOW - (now - recent[0])) + 1))
    try:
        t = await req.app["pve"].login(user, body.get("password", ""))
    except PVEError as e:
        if e.status == 401:
            fails[user.lower()] = recent + [now]
        raise
    fails.pop(user.lower(), None)
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


@routes.get("/api/login-settings")
async def get_login_settings(req):
    s = await session(req)
    return web.json_response({"settings": prefs.load_login(),
                              "can_edit": await req.app["pve"].can(s["ticket"], "/", "Sys.Modify")})


@routes.put("/api/login-settings")
async def put_login_settings(req):
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    return web.json_response(prefs.save_login(await req.json()))


# ---------------- error journal ----------------
@routes.post("/api/client-log")
async def client_log(req):
    """The screens report their own errors here, also before anyone has signed in."""
    seat = seat_of(req)
    s = req.app["sessions"].get(req.cookies.get(COOKIE))
    try:
        body = await req.json()
    except ValueError:
        raise web.HTTPBadRequest(text="bad json")
    errlog.client(body if isinstance(body, dict) else {}, seat, s["user"] if s else "")
    return web.json_response({"ok": True})


@routes.get("/api/logs")
async def get_logs(req):
    s = await session(req)
    pve = req.app["pve"]
    if not (await pve.can(s["ticket"], "/", "Sys.Audit") or await pve.can(s["ticket"], "/", "Sys.Modify")):
        raise PVEError(403, i18n._("forbidden"))
    return web.json_response({"entries": errlog.entries(), "file": errlog.LOG_FILE,
                              "can_clear": await pve.can(s["ticket"], "/", "Sys.Modify")})


@routes.delete("/api/logs")
async def clear_logs(req):
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    errlog.clear()
    log.info("error journal cleared by %s", s["user"])
    return web.json_response({"ok": True})


@routes.put("/api/prefs")
async def put_prefs(req):
    s = await session(req)
    try:
        body = await req.json()
    except ValueError:
        raise web.HTTPBadRequest(text="JSON expected")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="an object expected")
    return web.json_response(prefs.save(s["user"], body))


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
    typ, vmid, action = req.match_info["type"], vmid_of(req.match_info["vmid"]), req.match_info["action"]
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


KERNEL_PKG = re.compile(r"^(proxmox-kernel|pve-kernel|linux-image)-")


def summarize_updates(pkgs):
    """What /nodes/{node}/apt/update lists, reduced to what the widget shows."""
    out = [{"name": p.get("Package", ""), "old": p.get("OldVersion", ""), "new": p.get("Version", ""),
            "origin": p.get("Origin", "")} for p in pkgs or []]
    out.sort(key=lambda p: (p["origin"] != "Proxmox", p["name"]))
    return {"allowed": True, "count": len(out),
            "proxmox": sum(p["origin"] == "Proxmox" for p in out),
            "kernel": any(KERNEL_PKG.match(p["name"]) for p in out),
            "packages": out[:50]}


@routes.get("/api/node-updates")
async def node_updates(req):
    """Package updates waiting on this node, as Proxmox already knows them (its daily apt update);
    reading the list needs Sys.Modify on the node, like in the Proxmox web UI."""
    s = await session(req)
    pve, node = req.app["pve"], req.app["cfg"]["node"]
    if not await pve.can(s["ticket"], f"/nodes/{node}", "Sys.Modify"):
        return web.json_response({"allowed": False})
    return web.json_response(summarize_updates(await pve.get(s["ticket"], f"/nodes/{node}/apt/update")))


DISK_OK = {"PASSED", "OK"}
POOL_OK = {"ONLINE"}


def summarize_disks(disks, pools):
    """Physical disks (SMART health, SSD wearout as Proxmox reports it) and ZFS pools."""
    d = [{"dev": x.get("devpath", ""), "model": x.get("model") or x.get("vendor") or "", "type": x.get("type", ""),
          "size": x.get("size", 0), "health": str(x.get("health") or "UNKNOWN").upper(),
          "wearout": x.get("wearout") if isinstance(x.get("wearout"), (int, float)) else None}
         for x in disks or []]
    p = [{"name": x.get("name", ""), "health": str(x.get("health") or "UNKNOWN").upper(),
          "size": x.get("size", 0), "alloc": x.get("alloc", 0)} for x in pools or []]
    for x in d:
        x["ok"] = x["health"] in DISK_OK
    for x in p:
        x["ok"] = x["health"] in POOL_OK
    d.sort(key=lambda x: (x["ok"], x["dev"]))
    p.sort(key=lambda x: (x["ok"], x["name"]))
    return {"allowed": True, "disks": d, "pools": p,
            "problems": sum(not x["ok"] and x["health"] != "UNKNOWN" for x in d) + sum(not x["ok"] for x in p)}


async def disks_data(app, ticket):
    pve, node = app["pve"], app["cfg"]["node"]
    if not await pve.can(ticket, f"/nodes/{node}", "Sys.Audit"):
        return {"allowed": False}
    lst, zfs = await asyncio.gather(pve.get(ticket, f"/nodes/{node}/disks/list"),
                                    pve.get(ticket, f"/nodes/{node}/disks/zfs"), return_exceptions=True)
    if isinstance(lst, Exception):
        raise lst
    return summarize_disks(lst, [] if isinstance(zfs, Exception) else zfs)


@routes.get("/api/disks")
async def disks(req):
    """Disk health and ZFS pools of this node; needs Sys.Audit on the node, as in the Proxmox web UI."""
    s = await session(req)
    return web.json_response(await disks_data(req.app, s["ticket"]))


def summarize_backups(entries, guests, now, days):
    """Latest backup per guest from backup storage listings; guests with none, or only older
    than `days`, are "stale" and listed first."""
    last = {}
    seen = set()
    for e in entries or []:
        vol, vmid = e.get("volid"), e.get("vmid")
        if not vmid or vol in seen:
            continue
        seen.add(vol)
        r = last.setdefault(int(vmid), {"last": 0, "count": 0, "size": 0})
        r["count"] += 1
        r["size"] += e.get("size") or 0
        r["last"] = max(r["last"], e.get("ctime") or 0)
    out = []
    for g in guests or []:
        if g.get("template"):
            continue
        r = last.get(g["vmid"], {"last": 0, "count": 0, "size": 0})
        out.append({"vmid": g["vmid"], "name": g.get("name") or "", "type": g.get("type"), **r,
                    "stale": not r["last"] or now - r["last"] > days * 86400})
    out.sort(key=lambda x: (not x["stale"], x["last"], x["vmid"]))
    return {"allowed": True, "days": days, "guests": out, "stale": sum(x["stale"] for x in out)}


async def backups_data(app, ticket, days, guests=None):
    pve, node = app["pve"], app["cfg"]["node"]
    if guests is None:
        guests = await pve.get(ticket, "/cluster/resources", type="vm")
    stores = [x["storage"] for x in await pve.get(ticket, f"/nodes/{node}/storage", content="backup") or []
              if x.get("active")]
    lists = await asyncio.gather(*(pve.get(ticket, f"/nodes/{node}/storage/{quote(st, safe='')}/content", content="backup")
                                   for st in stores), return_exceptions=True)
    entries = [e for lst in lists if not isinstance(lst, Exception) for e in lst or []]
    return summarize_backups(entries, guests, time.time(), days)


@routes.get("/api/backups")
async def backups(req):
    """When each guest the user can see was last backed up, from the node's backup storages
    (local dumps and Proxmox Backup Server alike)."""
    s = await session(req)
    try:
        days = min(365, max(1, int(req.query.get("days", 7))))
    except ValueError:
        days = 7
    return web.json_response(await backups_data(req.app, s["ticket"], days))


def build_alerts(limits, host=None, storages=(), disks=None, backups=None, services=()):
    """What needs a look, worst first. Each alert is {level, kind, ...data}; the menu words it."""
    out = []
    for d in (disks or {}).get("disks", []):
        if not d["ok"] and d["health"] != "UNKNOWN":
            out.append({"level": "bad", "kind": "disk", "name": d["model"] or d["dev"], "dev": d["dev"], "health": d["health"]})
    for p in (disks or {}).get("pools", []):
        if not p["ok"]:
            out.append({"level": "bad", "kind": "pool", "name": p["name"], "health": p["health"]})
    for st in storages:
        pct = round(st["used"] / st["total"] * 100) if st.get("total") else 0
        if pct >= limits["storage_pct"]:
            out.append({"level": "bad" if pct >= 98 else "warn", "kind": "storage", "name": st["id"], "pct": pct})
    temp = (host or {}).get("temp")
    if temp is not None and temp >= limits["temp_c"]:
        out.append({"level": "bad" if temp >= limits["temp_c"] + 10 else "warn", "kind": "temp", "temp": temp})
    if backups and backups.get("stale"):
        never = sum(1 for g in backups["guests"] if g["stale"] and not g["last"])
        out.append({"level": "warn", "kind": "backup", "n": backups["stale"], "never": never, "days": backups["days"]})
    for svc in services:
        if svc.get("status") and svc["status"] != "running":
            out.append({"level": "warn", "kind": "service", "name": svc["name"], "guest": (svc.get("guest") or {}).get("name")})
    out.sort(key=lambda a: a["level"] != "bad")
    return out


@routes.get("/api/alerts")
async def alerts(req):
    """Disks, pools, full storages, host temperature, stale backups and services whose guest is down,
    in one list for the bell in the top bar. Every source is read with the user's own rights."""
    s = await session(req)
    t, pve, app = s["ticket"], req.app["pve"], req.app
    node, limits = app["cfg"]["node"], app["cfg"]["alerts"]
    guests = await pve.get(t, "/cluster/resources", type="vm") or []

    async def storages():
        res = await pve.get(t, f"/nodes/{node}/storage")
        return [{"id": r["storage"], "used": r.get("used", 0), "total": r.get("total", 0)}
                for r in res or [] if r.get("active") and r.get("total")]

    async def services():
        visible = {(g["type"], g["vmid"]): g for g in guests}
        out = []
        for svc in await app["services"].get():
            g = svc.get("guest")
            if g and (g["type"], g["vmid"]) in visible:
                out.append({**svc, "status": visible[(g["type"], g["vmid"])].get("status")})
        return out

    st, dk, bk, sv = await asyncio.gather(storages(), disks_data(app, t), backups_data(app, t, limits["backup_days"], guests),
                                          services(), return_exceptions=True)
    ok = lambda x, empty: empty if isinstance(x, Exception) else x  # noqa: E731  one source down must not hide the rest
    items = build_alerts(limits, app["stats"].snapshot(), ok(st, []), ok(dk, None), ok(bk, None), ok(sv, []))
    return web.json_response({"alerts": items, "bad": sum(a["level"] == "bad" for a in items)})


async def can_wake(req, ticket):
    node = req.app["cfg"]["node"]
    return await req.app["pve"].can(ticket, f"/nodes/{node}", "Sys.PowerMgmt")


@routes.get("/api/wol")
async def wol_list(req):
    """Machines that can be woken from here (config.yaml, `wol:`); for users who may power the node."""
    s = await session(req)
    if not await can_wake(req, s["ticket"]):
        return web.json_response({"allowed": False, "targets": []})
    return web.json_response({"allowed": True, "targets": [{"id": t["id"], "name": t["name"]} for t in wol.targets(req.app["cfg"])]})


@routes.post("/api/wol/{id}")
async def wol_wake(req):
    s = await session(req)
    if not await can_wake(req, s["ticket"]):
        raise PVEError(403, i18n._("forbidden"))
    tid = req.match_info["id"]
    target = next((t for t in wol.targets(req.app["cfg"]) if tid.isdigit() and t["id"] == int(tid)), None)
    if not target:
        raise web.HTTPNotFound()
    await asyncio.get_running_loop().run_in_executor(None, wol.send, target)
    log.info("wake-on-lan %s (%s) by %s", target["name"], target["mac"], s["user"])
    return web.json_response({"ok": True, "name": target["name"]})


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
    try:
        body = await req.json()
    except ValueError:
        raise web.HTTPBadRequest(text="JSON expected")
    if not isinstance(body, dict) or not isinstance(body.get("gpu"), str):
        raise web.HTTPBadRequest(text="vmid and gpu expected")
    job = await req.app["launcher"].launch(s["ticket"], seat_of(req), vmid_of(body.get("vmid")), body["gpu"])
    req.app["resources"].invalidate()
    return web.json_response(job.as_dict())


@routes.get("/api/jobs/{id}")
async def job(req):
    await session(req)
    jid = req.match_info["id"]
    j = req.app["launcher"].jobs.get(int(jid)) if jid.isdigit() else None
    if not j:
        raise web.HTTPNotFound()
    return web.json_response(j.as_dict())


@routes.post("/api/console/{vmid}")
async def console_open(req):
    """VNC ticket for a guest's screen (a VM's display, a container's terminal), issued with the
    user's own PVE ticket, so Proxmox checks VM.Console as usual. ?type=lxc for a container."""
    s = await session(req)
    vmid = vmid_of(req.match_info["vmid"])
    typ = req.query.get("type", "qemu")
    if typ not in ("qemu", "lxc"):
        raise web.HTTPBadRequest(text="bad type")
    node = req.app["cfg"]["node"]
    d = await req.app["pve"].post(s["ticket"], f"/nodes/{node}/{typ}/{vmid}/vncproxy", websocket=1)
    token = secrets.token_urlsafe(24)
    req.app["consoles"][token] = {"ticket": s["ticket"], "vmid": vmid, "type": typ, "port": d["port"],
                                  "vncticket": d["ticket"], "at": time.time()}
    return web.json_response({"token": token, "password": d["ticket"]})


@routes.get("/api/console/ws/{token}")
async def console_ws(req):
    """Relay the browser's noVNC websocket to PVE's vncwebsocket."""
    c = req.app["consoles"].pop(req.match_info["token"], None)
    if not c or time.time() - c["at"] > 60:
        raise web.HTTPForbidden(text="console token expired")
    node = req.app["cfg"]["node"]
    url = (f"wss://127.0.0.1:8006/api2/json/nodes/{node}/{c.get('type', 'qemu')}/{c['vmid']}/vncwebsocket"
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


@routes.get("/api/update")
async def update_status(req):
    s = await session(req)
    try:
        st = dict(await req.app["update"].get())
    except Exception as e:
        return web.json_response({"enabled": False, "error": str(e)})
    st["can_apply"] = await req.app["pve"].can(s["ticket"], "/", "Sys.Modify")
    return web.json_response(st)


@routes.post("/api/update/apply")
async def update_apply(req):
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    # A transient unit, so restarting pve-homelab during install.sh doesn't kill the update itself.
    await run("systemd-run", "--unit=pve-homelab-update-now", "--collect", "--quiet",
              "--setenv=PYTHONPATH=/opt/pve-homelab/backend", "/usr/bin/python3", "-m", "pvehomelab.update", "apply")
    log.info("update started by %s", s["user"])
    return web.json_response({"ok": True})


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
    if not cfg["seats"]:
        # No seats configured: every host-driven GPU with a monitor gets one.
        from .setup import detect_seats
        for i, g in enumerate(await detect_seats()):
            cfg["seats"]["igpu" if g["integrated"] else f"gpu{i}"] = {"title": g["name"], "gpu": g["pci"], "tty": 7 + i, "kiosk": True}
        log.info("auto-detected seats: %s", list(cfg["seats"]))
    app["pve"] = PVE()
    app["stats"] = HostStats()
    app["ddc"] = DDC(cfg["monitors"])
    app["sessions"] = {}
    app["consoles"] = {}
    app["host_ip"] = _host_ip()
    app["allowed_hosts_cache"] = allowed_hosts(app)
    app["login_fails"] = {}
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

    async def find_services():
        res = await app["resources"].get()
        ips = await caddy.guest_ips(cfg["node"], res)
        return await discover.discover(cfg, res, ips, app["host_ip"])
    # Probing every guest takes a few seconds: refresh in the background every 5 minutes.
    app["discovered"] = Cached(find_services, 300, stale=True)

    async def build_services():
        res = await app["resources"].get()
        ips = await caddy.guest_ips(cfg["node"], res)
        listed = caddy.build(cfg, await caddy.routes(cfg), ips, app["host_ip"])
        try:
            found = await app["discovered"].get()
        except Exception as e:
            log.warning("discovery failed: %s", e)
            found = []
        return discover.merge(listed, found)
    app["services"] = Cached(build_services, 60, stale=True)

    async def check_update():
        return await update.status(cfg)
    app["update"] = Cached(check_update, max(1, float(update.settings(cfg)["check_hours"])) * 3600, stale=True)

    app["launcher"] = Launcher(app)
    app["tasks"] = [asyncio.create_task(app["stats"].loop()),
                    asyncio.create_task(app["launcher"].watch_loop()),
                    asyncio.create_task(housekeeping_loop(app)),
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


SESSION_IDLE = 2 * 3600   # a Proxmox ticket can't be renewed after 2 h anyway
CONSOLE_TOKEN_TTL = 60
JOB_TTL = 600


def housekeeping(app, now=None):
    """Forget what nobody can use any more: idle sessions, unused console tokens, old launch
    jobs and stale login failures."""
    now = now or time.time()
    for sid in [k for k, v in app["sessions"].items() if now - v["seen"] > SESSION_IDLE]:
        del app["sessions"][sid]
    for tok in [k for k, v in app["consoles"].items() if now - v["at"] > CONSOLE_TOKEN_TTL]:
        del app["consoles"][tok]
    jobs = app["launcher"].jobs
    for jid in [k for k, j in jobs.items() if j.done and now - j.created > JOB_TTL]:
        del jobs[jid]
    fails = app["login_fails"]
    for user in [k for k, v in fails.items() if not v or now - v[-1] > LOGIN_WINDOW]:
        del fails[user]


async def housekeeping_loop(app):
    while True:
        await asyncio.sleep(60)
        try:
            housekeeping(app)
        except Exception as e:
            log.warning("housekeeping: %s", e)


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
    errlog.setup()
    app = web.Application(middlewares=[errors, guard])
    app.on_response_prepare.append(_no_stale_code)
    app["cfg"] = config.load()
    app["code"] = {k: update.installed()[k] for k in ("version", "commit")}  # what this process runs
    app.add_routes(routes)
    app.router.add_static("/", config.WEB_DIR, show_index=False, append_version=False)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
