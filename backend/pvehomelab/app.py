import asyncio
import glob
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from urllib.parse import quote

import aiohttp
from aiohttp import web

from . import caddy, config, designs, discover, errlog, feedback, gpus as G, i18n, icons, prefs, settings, update, userwidgets, weather, wol
from .ddc import DDC
from .host import HostStats
from .launch import Launcher
from .pve import PVE, TFA_KINDS, PVEError, TfaChallenge
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


def peer(req):
    return (req.remote or "").removeprefix("::ffff:")


def is_remote(req):
    """Anything but the host itself: a browser coming through the reverse proxy (see gate)."""
    p = peer(req)
    return not (p.startswith("127.") or p == "::1")


def client_ip(req):
    """Who is at the other end: behind the proxy it says so in X-Forwarded-For (only the proxy gets this far)."""
    if not is_remote(req):
        return peer(req)
    return req.headers.get("X-Forwarded-For", "").split(",")[0].strip() or peer(req)


def over_https(req):
    """The browser reached us over HTTPS: directly, or through the proxy, which says so."""
    if req.secure:
        return True
    return is_remote(req) and req.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"


def seat_of(req):
    seats = req.app["cfg"]["seats"]
    # A browser elsewhere is always the "web" seat, whatever it asks for: only the screens
    # plugged into this host may switch monitors or hand their GPU to a VM.
    if is_remote(req):
        if "web" not in seats:
            raise web.HTTPForbidden(text="web access is off")
        return "web"
    seat = req.query.get("seat") or req.headers.get("X-Seat") or ""
    if not seat:   # a browser on the host itself, without ?seat=: the first kiosk seat
        seat = next((k for k, s in seats.items() if s.get("kiosk")), next(iter(seats), ""))
    if seat not in seats:
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


async def maybe_session(req):
    """The session if this browser is signed in, else None (for pages that work either way)."""
    try:
        return await session(req)
    except web.HTTPUnauthorized:
        return None


async def require(req, s, priv, path="/"):
    """The signed-in user holds `priv` on `path` in Proxmox, or the request ends with 403."""
    if not await req.app["pve"].can(s["ticket"], path, priv):
        raise PVEError(403, i18n._("forbidden"))


SIGN_IN_LEVELS = ("minimal", "users", "full")


def sign_in_level(req):
    """How much the sign-in screen tells a browser that hasn't signed in. The screens plugged into
    the host show everything; a browser elsewhere gets web.sign_in: "minimal" (no people, no host
    figures), "users" (the people too) or "full" (all of it, as on the host)."""
    if not is_remote(req):
        return "full"
    level = (req.app["cfg"].get("web") or {}).get("sign_in", "minimal")
    return level if level in SIGN_IN_LEVELS else "minimal"


async def visible_guests(req, s):
    """{(type, vmid): resource row} of the guests this user may see."""
    rows = await req.app["pve"].get(s["ticket"], "/cluster/resources", type="vm") or []
    return {(g["type"], g["vmid"]): g for g in rows}


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
async def gate(req, handler):
    """The backend listens beyond loopback only for the reverse proxy (web.allow_from): any other
    caller is refused before anything else looks at the request."""
    if is_remote(req):
        w = req.app["cfg"]["web"]
        try:
            ip = ipaddress.ip_address(peer(req))
            ok = bool(w.get("enabled")) and any(ip in ipaddress.ip_network(str(n), strict=False)
                                                for n in w.get("allow_from") or [])
        except ValueError:
            ok = False
        if not ok:
            return web.Response(status=403, text="forbidden")
    return await handler(req)


@web.middleware
async def guard(req, handler):
    """The menu is meant for this machine. A web page elsewhere must not reach it through a
    rebound DNS name (wrong Host), nor post to it from its own origin (wrong Origin).
    Through the reverse proxy (the only remote caller gate lets in) the Host is the proxy's own
    site name, which the proxy chose to send here: it is trusted, and an Origin must match it."""
    hosts = req.app.get("allowed_hosts_cache") or allowed_hosts(req.app)
    if "*" not in hosts:
        host = _hostname(req.headers.get("Host", ""))
        proxied = is_remote(req)
        if not proxied and host not in hosts:
            return err(421, "unknown host")
        origin = req.headers.get("Origin")
        ok_origins = (hosts | {host}) if proxied else hosts
        if req.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != "null" \
                and _hostname(origin) not in ok_origins:
            return err(403, "cross-origin request refused")
    return await handler(req)


# Which feature each part of the API belongs to: (method or "*", path prefix or pattern, feature).
FEATURE_ROUTES = [
    ("*", "/api/alerts", "alerts"),
    ("*", "/api/node-updates", "node_updates"),
    ("*", "/api/update", "app_updates"),
    ("*", "/api/weather", "weather"),
    ("*", "/api/console", "consoles"),
    ("POST", re.compile(r"^/api/guests/[a-z]+/\d+/[a-z]+$"), "guest_actions"),
    ("PUT", re.compile(r"^/api/guests/[a-z]+/\d+/config$"), "guest_settings"),
    ("*", "/api/host/power", "host_power"),
    ("*", "/api/wol", "wol"),
    ("POST", "/api/designs", "my_designs"),
    ("DELETE", "/api/designs/", "my_designs"),
    ("POST", "/api/widgets", "my_widgets"),
    ("DELETE", "/api/widgets/", "my_widgets"),
]


def feature_on(app, name):
    return (app["cfg"].get("features") or {}).get(name, True) is not False


def feature_of(method, path):
    for m, where, name in FEATURE_ROUTES:
        if m not in ("*", method):
            continue
        if hasattr(where, "match"):
            if where.match(path):
                return name
        elif path == where or path.startswith(where if where.endswith("/") else where + "/"):
            return name
    return None


@web.middleware
async def features(req, handler):
    """A part of the menu switched off in Settings → System → Components is gone from the API too."""
    name = feature_of(req.method, req.path)
    if name and not feature_on(req.app, name):
        return web.json_response({"error": i18n._("feature_off")}, status=404)
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
    s = await maybe_session(req)
    level = "full" if s else sign_in_level(req)
    full = level == "full"
    if s:   # signed in: the guests this person may see
        guests = [g for g in (await visible_guests(req, s)).values() if not g.get("template")]
    else:   # the screen plugged into the host (or web.sign_in: full): all of them
        guests = [g for g in await app["resources"].get() if not g.get("template")] if full else []
    return web.json_response({
        "node": cfg["node"],
        "demo": app.get("demo", False),
        "app": {"version": update.installed()["version"], "repo": update.settings(cfg)["repo"]},
        "version": app["pveversion"] if full else "",
        "ip": app["host_ip"] if full else "",
        "seat": {"id": seat, **cfg["seats"][seat],
                 "gpu_name": await G.pretty_name(cfg["seats"][seat]["gpu"]) if cfg["seats"][seat].get("gpu") else ""},
        "stats": full,   # host figures before sign-in: the host and network widgets may show
        "host": app["stats"].snapshot() if full else None,
        "guests": {"running": sum(g.get("status") == "running" for g in guests),
                   "stopped": sum(g.get("status") != "running" for g in guests)} if full else None,
        "users": pve_users(app) if level != "minimal" else [],
        "language": cfg["language"],
        "languages": languages(),
        "systems_tag": cfg["systems_tag"],
        "weather": cfg["weather"],
        "saver_after_min": cfg["saver"]["after_min"],
        "lock_after_min": cfg["lock_after_min"],
        # looks come from the designs folders (built-in and yours), see designs.py
        "themes": designs.catalog("themes"),
        "backgrounds": designs.catalog("backgrounds"),
        "clocks": designs.catalog("clocks"),
        "fonts": designs.catalog("fonts"),
        "widget_styles": [m["id"] for m in designs.catalog("widgets")],
        "designer": designer_mode(app),
        "feedback": feedback_cfg(cfg)["enabled"],
        "features": {f: feature_on(app, f) for f in settings.FEATURES},
        "login": prefs.load_login(),
        "widgets": userwidgets.all_ids(),
    })


# ---------------- design files ----------------
# Same URLs as when they lived in web/: served from the designs folders, yours first.
DESIGN_ID = r"{did:[a-z0-9][a-z0-9_-]{0,63}}"


async def design_file(kind, did):
    p = designs.path_of(kind, did)
    if not p:
        raise web.HTTPNotFound()
    return web.FileResponse(p)


@routes.get("/{kind:themes|backgrounds|fonts}/" + DESIGN_ID + ".css")
async def design_css(req):
    return await design_file(req.match_info["kind"], req.match_info["did"])


@routes.get("/clocks/" + DESIGN_ID + ".js")
async def design_clock(req):
    return await design_file("clocks", req.match_info["did"])


@routes.get("/widgets/" + DESIGN_ID + "/widget.css")
async def design_widget(req):
    return await design_file("widgets", req.match_info["did"])


@routes.get("/widgets/i18n.json")
async def widget_strings(req):
    """Every widget's strings from its i18n/<lang>.json files: {id: {lang: {key: text}}}."""
    data = await asyncio.get_running_loop().run_in_executor(None, userwidgets.translations)
    return web.json_response(data, headers={"Cache-Control": "no-cache"})


@routes.get("/widgets/" + DESIGN_ID + "/widget.js")
async def widget_code(req):
    """A widget's logic: the built-in one, or yours from /etc/pve-homelab/widgets."""
    p = userwidgets.path_of(req.match_info["did"])
    if not p:
        raise web.HTTPNotFound()
    # revalidated every time: a widget reinstalled under the same id must not come from the cache
    return web.FileResponse(p, headers={"Cache-Control": "no-cache"})


@routes.get("/api/weather")
async def get_weather(req):
    cfg = req.app["cfg"]["weather"]
    city = (req.query.get("city") or cfg["city"])[:100]
    units = req.query.get("units") or cfg["units"]
    if is_remote(req) and not await maybe_session(req):
        city, units = cfg["city"], cfg["units"]   # a stranger's browser can't make us ask about any city
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
    if sign_in_level(req) != "full":
        await session(req)
    return web.json_response(req.app["stats"].snapshot())


@routes.get("/icons/{slug}.svg")
async def icon(req):
    data = await icons.get(req.match_info["slug"])
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


# ---------------- session ----------------
LOGIN_TRIES, LOGIN_WINDOW = 5, 60  # wrong passwords per user name per minute
LOGIN_TRIES_PER_PLACE = 20         # ... and from one address (or one screen on the host), any names
TFA_TTL, TFA_TRIES = 110, 5        # s to answer the second factor; codes per challenge


def _place(req):
    """Where a sign-in comes from, for the limit: the screen on the host, or the browser's address."""
    return f"seat:{seat_of(req)}" if not is_remote(req) else f"ip:{client_ip(req)}"


def _check_limits(req, user):
    """Too many wrong answers lately for this name, or from this place: wait."""
    fails, now = req.app["login_fails"], time.time()
    for key, most in ((user.lower(), LOGIN_TRIES), (_place(req), LOGIN_TRIES_PER_PLACE)):
        recent = [x for x in fails.get(key, []) if now - x < LOGIN_WINDOW]
        if len(recent) >= most:
            raise web.HTTPTooManyRequests(text=i18n._("too_many_logins", s=int(LOGIN_WINDOW - (now - recent[0])) + 1))


def _failed(req, user):
    fails, now = req.app["login_fails"], time.time()
    for key in (user.lower(), _place(req)):
        fails[key] = [x for x in fails.get(key, []) if now - x < LOGIN_WINDOW] + [now]


@routes.post("/api/login")
async def login(req):
    body = await req.json()
    seat = seat_of(req)
    user = str(body.get("user", ""))
    _check_limits(req, user)
    try:
        t = await req.app["pve"].login(user, body.get("password", ""))
    except PVEError as e:
        if e.status == 401:
            _failed(req, user)
        raise
    if isinstance(t, TfaChallenge):
        # The password was right; the session waits for the second factor, kept here, not in the browser.
        cid = secrets.token_urlsafe(24)
        req.app["tfa"][cid] = {"ch": t, "seat": seat, "place": _place(req), "until": time.time() + TFA_TTL, "tries": 0}
        usable = [m for m in t.methods if m in TFA_KINDS]
        return web.json_response({"tfa": {"id": cid, "methods": usable, "ttl": TFA_TTL,
                                          "webauthn_only": not usable and "webauthn" in t.methods}})
    return await _start_session(req, t, seat)


@routes.post("/api/login/tfa")
async def login_tfa(req):
    body = await req.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON object expected")
    pending = req.app["tfa"]
    c = pending.get(str(body.get("id", "")))
    if not c or c["seat"] != seat_of(req) or c["place"] != _place(req):
        raise PVEError(404, i18n._("tfa_gone"))
    if time.time() > c["until"]:
        pending.pop(str(body["id"]), None)
        raise PVEError(410, i18n._("tfa_gone"))
    kind, code = str(body.get("kind", "")), str(body.get("code", "")).strip().replace(" ", "")
    if kind not in TFA_KINDS or kind not in c["ch"].methods or not code or len(code) > 128:
        raise web.HTTPBadRequest(text="kind and code expected")
    _check_limits(req, c["ch"].user)
    try:
        t = await req.app["pve"].finish_tfa(c["ch"], kind, code)
    except PVEError as e:
        if e.status == 401:
            _failed(req, c["ch"].user)
            c["tries"] += 1
            if c["tries"] >= TFA_TRIES:
                pending.pop(str(body["id"]), None)
                raise PVEError(410, i18n._("tfa_too_many"))
        raise
    pending.pop(str(body["id"]), None)
    return await _start_session(req, t, c["seat"])


async def _start_session(req, t, seat):
    req.app["login_fails"].pop(t.user.lower(), None)
    sid = secrets.token_urlsafe(32)
    req.app["sessions"][sid] = {"ticket": t, "seat": seat, "user": t.user, "seen": time.time()}
    admin = await req.app["pve"].can(t, "/", "Sys.Modify")
    resp = web.json_response({"user": t.user, "prefs": prefs.load(t.user), "admin": admin})
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="Strict", path="/", secure=over_https(req))
    log.info("login %s on seat %s from %s", t.user, seat, client_ip(req))
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
    admin = await req.app["pve"].can(s["ticket"], "/", "Sys.Modify")
    return web.json_response({"user": s["user"], "prefs": prefs.load(s["user"]), "admin": admin})


# ---------------- your own designs ----------------
async def designs_admin(req):
    """Designs and widgets change the menu for everyone on the host (and clocks and widgets are
    code that runs in it): admins only."""
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    return s


@routes.get("/api/designs")
async def designs_list(req):
    await session(req)
    worn = prefs.usage()
    mine = designs.mine()
    for d in mine:   # how many wear it (a pack: its theme or any of its parts), so removing it can say so
        d["worn"] = max([worn.get((d["kind"], d["id"]), 0)] + [worn.get((p["kind"], p["id"]), 0) for p in d.get("parts", [])])
    return web.json_response({"mine": mine, "folder": config.USER_DESIGNS_DIR})


async def uploaded_files(req):
    """[(filename, bytes)] of a multipart form, at most designs.MAX_TOTAL in all."""
    files, total = [], 0
    try:
        reader = await req.multipart()
    except (AssertionError, ValueError, KeyError):
        raise web.HTTPBadRequest(text="multipart form expected")
    async for part in reader:
        if not part.filename:
            continue
        data = bytearray()
        while chunk := await part.read_chunk(64 * 1024):
            data += chunk
            total += len(chunk)
            if total > designs.MAX_TOTAL:
                raise web.HTTPRequestEntityTooLarge(max_size=designs.MAX_TOTAL, actual_size=total)
        files.append((part.filename, bytes(data)))
    return files


@routes.post("/api/designs")
async def designs_install(req):
    """One or more designs (.css, .js, or a .zip of them) as multipart files."""
    s = await designs_admin(req)
    files = await uploaded_files(req)
    try:
        done = await asyncio.get_running_loop().run_in_executor(None, designs.install, files)
    except designs.DesignError as e:
        raise web.HTTPBadRequest(text=str(e))
    log.info("designs installed by %s: %s", s["user"], ", ".join(f"{d['kind']}/{d['id']}" for d in done))
    return web.json_response({"installed": done})


def designer_mode(app):
    """Live reload of designs: in the demo, or on a host with `designer: true` in config.yaml."""
    return bool(app.get("demo") or app["cfg"].get("designer"))


@routes.get("/api/designs/events")
async def designs_events(req):
    """Server-sent events while designing: one whenever a design file is changed, added or removed,
    so the page swaps the stylesheet or clock without reloading (designer.js)."""
    if not designer_mode(req.app):
        raise web.HTTPNotFound()
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(req)
    loop = asyncio.get_running_loop()

    def both():
        return designs.snapshot(), userwidgets.snapshot()

    prev, quiet = await loop.run_in_executor(None, both), 0
    stop = req.app["stopping"]  # the server is shutting down: end the stream instead of holding it up
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), 1)
                break
            except asyncio.TimeoutError:
                pass
            cur = await loop.run_in_executor(None, both)
            if cur != prev:
                d = designs.changes(prev[0], cur[0])
                if cur[1] != prev[1]:
                    d["catalog"] = True  # a widget's code changed: only a reload picks it up
                await resp.write(f"data: {json.dumps(d)}\n\n".encode())
                prev, quiet = cur, 0
            elif (quiet := quiet + 1) >= 15:
                await resp.write(b": still here\n\n")
                quiet = 0
    except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
        pass
    return resp


@routes.delete("/api/designs/{kind}/{did}")
async def designs_remove(req):
    s = await designs_admin(req)
    kind, did = req.match_info["kind"], req.match_info["did"]
    # ?pack=1 on a theme: with the background and clock it brings (DESIGNS.md, "A theme as a whole")
    gone = designs.remove_pack(did) if kind == "themes" and req.query.get("pack") == "1" \
        else [(kind, did)] if designs.remove(kind, did) else []
    if not gone:
        raise web.HTTPNotFound(text="no such design of yours")
    log.info("designs removed by %s: %s", s["user"], ", ".join(f"{k}/{i}" for k, i in gone))
    return web.json_response({"ok": True, "removed": [{"kind": k, "id": i} for k, i in gone]})


# ---------------- your own widgets ----------------
@routes.get("/api/widgets")
async def widgets_list(req):
    await session(req)
    return web.json_response({"mine": userwidgets.mine(), "folder": config.USER_WIDGETS_DIR})


@routes.post("/api/widgets")
async def widgets_install(req):
    """One or more widgets: <id>.js (+ <id>.css, its look), or a .zip of <id>/widget.js
    (+ <id>/widget.css). A widget is code that runs in the menu: admins only."""
    s = await designs_admin(req)
    files = await uploaded_files(req)
    try:
        done = await asyncio.get_running_loop().run_in_executor(None, userwidgets.install, files)
    except userwidgets.WidgetError as e:
        raise web.HTTPBadRequest(text=str(e))
    log.info("widgets installed by %s: %s", s["user"], ", ".join(d["id"] for d in done))
    return web.json_response({"installed": done})


@routes.delete("/api/widgets/{wid}")
async def widgets_remove(req):
    s = await designs_admin(req)
    wid = req.match_info["wid"]
    if not userwidgets.remove(wid):
        raise web.HTTPNotFound(text="no such widget of yours")
    log.info("widget %s removed by %s", wid, s["user"])
    return web.json_response({"ok": True})


# ---------------- writing to the author ----------------
def feedback_cfg(cfg):
    """`feedback:` in config.yaml, as {enabled, repo}; `feedback: false` turns it off."""
    fb = cfg.get("feedback")
    if isinstance(fb, bool):
        return {"enabled": fb, "repo": ""}
    fb = fb if isinstance(fb, dict) else {}
    return {"enabled": fb.get("enabled", True) is not False, "repo": str(fb.get("repo") or "")}


async def feedback_known(app):
    """Names this host knows of, to take out of what is sent: node, users, guests, services."""
    out = [(app["cfg"]["node"], "<node>"), (app.get("host_ip") or "", "<ip>")]
    for u in pve_users(app):
        out += [(u["id"], "<user>"), (u.get("name") or "", "<user>"), (u.get("full") or "", "<user>")]
    try:
        out += [(g.get("name") or "", "<guest>") for g in await app["resources"].get()]
        for svc in await app["services"].get():
            out += [(svc.get("host") or "", "<host>"), ((svc.get("upstream") or "").split(":")[0], "<ip>")]
    except Exception as e:  # what is known so far is still taken out; the patterns catch the rest
        log.warning("feedback: names to remove not all known: %s", e)
    return [x for x in out if x[0]]


@routes.post("/api/feedback")
async def feedback_compose(req):
    """The issue as it will be sent, its link and a QR code of the link. Nothing leaves the host:
    the person opens the link and submits it on GitHub."""
    s = await session(req)
    app, cfg = req.app, req.app["cfg"]
    fb = feedback_cfg(cfg)
    if not fb["enabled"]:
        raise web.HTTPNotFound()
    try:
        b = await req.json()
    except ValueError:
        b = {}
    if not isinstance(b, dict):
        b = {}
    pve = app["pve"]
    can_journal = await pve.can(s["ticket"], "/", "Sys.Audit") or await pve.can(s["ticket"], "/", "Sys.Modify")
    known = await feedback_known(app)
    env = feedback.environment(app["code"], app["pveversion"], b.get("client"), app.get("demo", False)) if b.get("env") else None
    journal, total = None, 0
    if b.get("journal") and can_journal:
        entries = errlog.entries()
        journal, total = feedback.journal_lines(entries, known), len(entries)
    repo = update._repo_slug(fb["repo"]) if fb["repo"] else update.settings(cfg)["repo"]
    out = await asyncio.get_running_loop().run_in_executor(
        None, feedback.compose, repo, b.get("kind"), b.get("title"), b.get("text"), env, journal, total)
    out["journal_allowed"] = can_journal
    return web.json_response(out)


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


RRD_TIMEFRAMES = ("hour", "day", "week")


def summarize_rrd(rows):
    """Proxmox rrddata rows -> parallel series for the charts. A guest that was off has no
    values for those points: they stay None (a gap), not zero."""
    def col(key, scale=1.0):
        return [None if r.get(key) is None else round(float(r[key]) * scale, 3) for r in rows]
    rows = sorted((r for r in rows or [] if r.get("time")), key=lambda r: r["time"])
    maxmem = next((r["maxmem"] for r in reversed(rows) if r.get("maxmem")), 0)
    return {"time": [int(r["time"]) for r in rows], "cpu": col("cpu", 100), "mem": col("mem"), "maxmem": maxmem,
            "netin": col("netin"), "netout": col("netout"), "diskread": col("diskread"), "diskwrite": col("diskwrite")}


@routes.get("/api/guests/{type}/{vmid}/rrd")
async def guest_rrd(req):
    """A guest's load over the last hour/day/week, with the user's own ticket (Proxmox checks VM.Audit)."""
    s = await session(req)
    typ, vmid = req.match_info["type"], vmid_of(req.match_info["vmid"])
    if typ not in ("qemu", "lxc"):
        raise web.HTTPBadRequest(text="bad type")
    tf = req.query.get("timeframe", "hour")
    if tf not in RRD_TIMEFRAMES:
        raise web.HTTPBadRequest(text="bad timeframe")
    node = req.app["cfg"]["node"]
    rows = await req.app["pve"].get(s["ticket"], f"/nodes/{node}/{typ}/{vmid}/rrddata", timeframe=tf, cf="AVERAGE")
    return web.json_response({"timeframe": tf, **summarize_rrd(rows)})


def summarize_snapshots(rows):
    """Proxmox's snapshot list without the "current" pseudo-entry, newest first."""
    out = [{"name": r.get("name", ""), "time": int(r.get("snaptime") or 0),
            "desc": (r.get("description") or "").strip()[:200], "ram": bool(r.get("vmstate"))}
           for r in rows or [] if r.get("name") and r.get("name") != "current"]
    return sorted(out, key=lambda r: -r["time"])


@routes.get("/api/guests/{type}/{vmid}/info")
async def guest_info(req):
    """For a guest's dialog: its snapshots and its latest backup, each read with the user's own
    rights; what the user may not see comes back as null rather than an error."""
    s = await session(req)
    typ, vmid = req.match_info["type"], vmid_of(req.match_info["vmid"])
    if typ not in ("qemu", "lxc"):
        raise web.HTTPBadRequest(text="bad type")
    pve, node, t = req.app["pve"], req.app["cfg"]["node"], s["ticket"]
    guests = [g for g in await pve.get(t, "/cluster/resources", type="vm") or [] if g.get("vmid") == vmid]
    if not guests:
        raise web.HTTPNotFound(text="no such guest")
    snaps, bk = await asyncio.gather(pve.get(t, f"/nodes/{node}/{typ}/{vmid}/snapshot"),
                                     backups_data(req.app, t, 365, guests), return_exceptions=True)
    backup = None
    if not isinstance(bk, Exception) and bk["guests"]:
        g = bk["guests"][0]
        backup = {"last": g["last"], "count": g["count"], "size": g["size"]}
    return web.json_response({"snapshots": None if isinstance(snaps, Exception) else summarize_snapshots(snaps),
                              "backup": backup})


# ---------------- a guest's resources and options, changed with the user's own rights ----------------
TAG = re.compile(r"^[a-z0-9_][a-z0-9_.+-]{0,31}$")
GUEST_PRIVS = (("memory", "VM.Config.Memory"), ("cpu", "VM.Config.CPU"), ("options", "VM.Config.Options"))


def parse_startup(value):
    """Proxmox "order=2,up=30,down=60" -> {"order": 2, "up": 30, "down": 60}."""
    out = {}
    for part in str(value or "").split(","):
        k, _, v = part.partition("=")
        if k.strip() in ("order", "up", "down") and v.strip().isdigit():
            out[k.strip()] = int(v)
    return out


def guest_settings(typ, conf, pending=()):
    """The part of a guest's config the menu edits, in plain values."""
    return {
        "type": typ,
        "memory": int(conf.get("memory") or 512),
        "balloon": (int(conf["balloon"]) if str(conf.get("balloon", "")).isdigit() else None) if typ == "qemu" else None,
        "swap": int(conf.get("swap") or 0) if typ == "lxc" else None,
        "cores": int(conf.get("cores") or 1),
        "sockets": int(conf.get("sockets") or 1) if typ == "qemu" else 1,
        "onboot": str(conf.get("onboot", "0")) == "1",
        "startup": parse_startup(conf.get("startup")),
        "tags": [x for x in re.split(r"[;, ]+", str(conf.get("tags") or "")) if x],
        "description": str(conf.get("description") or ""),
        "passthrough": any(k.startswith("hostpci") for k in conf),
        "pending": sorted(pending),
    }


def guest_changes(typ, body):
    """A body from the guest dialog -> (PVE config fields, fields to delete); 400 on anything odd."""
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON object expected")
    data, delete = {}, []

    def num(key, lo, hi):
        v = body[key]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise web.HTTPBadRequest(text=f"{key}: {lo}…{hi}")
        return v
    if "memory" in body:
        data["memory"] = num("memory", 16, 4 * 1024 * 1024)
    if "cores" in body:
        data["cores"] = num("cores", 1, 512)
    if typ == "qemu" and "balloon" in body:
        if body["balloon"] is None:
            delete.append("balloon")
        else:
            data["balloon"] = num("balloon", 0, 4 * 1024 * 1024)
    if typ == "lxc" and "swap" in body:
        data["swap"] = num("swap", 0, 4 * 1024 * 1024)
    if "onboot" in body:
        if not isinstance(body["onboot"], bool):
            raise web.HTTPBadRequest(text="onboot: true or false")
        data["onboot"] = 1 if body["onboot"] else 0
    if "startup" in body:
        st = body["startup"] or {}
        if not isinstance(st, dict):
            raise web.HTTPBadRequest(text="startup: {order, up, down}")
        parts = []
        for k, hi in (("order", 9999), ("up", 86400), ("down", 86400)):
            v = st.get(k)
            if v in (None, ""):
                continue
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= hi:
                raise web.HTTPBadRequest(text=f"startup.{k}: 0…{hi}")
            parts.append(f"{k}={v}")
        if parts:
            data["startup"] = ",".join(parts)
        else:
            delete.append("startup")
    if "tags" in body:
        tags = body["tags"]
        if not isinstance(tags, list) or len(tags) > 32 or not all(isinstance(x, str) and TAG.match(x) for x in tags):
            raise web.HTTPBadRequest(text="tags: lower-case words")
        if tags:
            data["tags"] = ";".join(dict.fromkeys(tags))
        else:
            delete.append("tags")
    if "description" in body:
        d = body["description"]
        if not isinstance(d, str) or len(d) > 8192 or "\0" in d:
            raise web.HTTPBadRequest(text="description: text up to 8 KB")
        if d.strip():
            data["description"] = d
        else:
            delete.append("description")
    if not data and not delete:
        raise web.HTTPBadRequest(text="nothing to change")
    if "memory" in data and data.get("balloon", 0) > data["memory"]:
        raise web.HTTPBadRequest(text="balloon: not above memory")
    return data, delete


async def _guest_settings(req, s, typ, vmid):
    pve, node, t = req.app["pve"], req.app["cfg"]["node"], s["ticket"]
    conf = await pve.get(t, f"/nodes/{node}/{typ}/{vmid}/config")
    pending = []
    if typ == "qemu":
        try:
            pending = [p["key"] for p in await pve.get(t, f"/nodes/{node}/qemu/{vmid}/pending") or []
                       if "pending" in p or p.get("delete")]
        except PVEError:
            pass
    can = {k: await pve.can(t, f"/vms/{vmid}", p) for k, p in GUEST_PRIVS}
    return {**guest_settings(typ, conf or {}, pending), "can": can}


@routes.get("/api/guests/{type}/{vmid}/config")
async def guest_config(req):
    s = await session(req)
    typ, vmid = req.match_info["type"], vmid_of(req.match_info["vmid"])
    if typ not in ("qemu", "lxc"):
        raise web.HTTPBadRequest(text="bad type")
    return web.json_response(await _guest_settings(req, s, typ, vmid))


@routes.put("/api/guests/{type}/{vmid}/config")
async def guest_config_put(req):
    """Memory, cores, start at boot and its order, tags, notes: written with the user's own ticket,
    so Proxmox itself decides (VM.Config.Memory, VM.Config.CPU, VM.Config.Options). A container takes
    them at once; a running VM keeps the new memory and cores pending until its next start."""
    s = await session(req)
    typ, vmid = req.match_info["type"], vmid_of(req.match_info["vmid"])
    if typ not in ("qemu", "lxc"):
        raise web.HTTPBadRequest(text="bad type")
    try:
        body = await req.json()
    except ValueError:
        body = None
    data, delete = guest_changes(typ, body)
    if delete:
        data["delete"] = ",".join(delete)
    await req.app["pve"].req(s["ticket"], "PUT", f"/nodes/{req.app['cfg']['node']}/{typ}/{vmid}/config", data)
    req.app["resources"].invalidate()
    log.info("%s changed %s %s: %s", s["user"], typ, vmid, ", ".join(sorted(k for k in data if k != "delete") + delete))
    return web.json_response(await _guest_settings(req, s, typ, vmid))


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
    visible = await visible_guests(req, s)
    out = []
    for svc in data:
        g = svc["guest"]
        if g and g["type"] == "node":
            st = "running"
        elif g:
            if (g["type"], g["vmid"]) not in visible:
                continue   # a service of a guest this person may not see is not theirs to see either
            st = visible[(g["type"], g["vmid"])].get("status")
        else:
            st = None      # a link, or something beyond this host
        out.append({**svc, "status": st})
    return web.json_response(out)


@routes.get("/api/storage")
async def storage(req):
    s = await session(req)
    node = req.app["cfg"]["node"]
    res = await req.app["pve"].get(s["ticket"], f"/nodes/{node}/storage")
    return web.json_response([{"id": r["storage"], "type": r.get("type"), "used": r.get("used", 0),
                               "total": r.get("total", 0)} for r in res or [] if r.get("active") and r.get("total")])


# A kernel has its version in the name (proxmox-kernel-7.0, proxmox-kernel-7.0.14-26-pve-signed);
# proxmox-kernel-helper is not one and needs no reboot.
KERNEL_PKG = re.compile(r"^(proxmox-kernel|pve-kernel|linux-image)-\d")
HEADLINE_PKG = ("pve-manager", "proxmox-ve", "qemu-server", "pve-qemu-kvm", "pve-container", "proxmox-backup-server")
CEPH_PKG = re.compile(r"^(ceph|libceph|librados|libradosstriper|librbd|librgw|libsqlite3-mod-ceph|python3-(ceph|rados|rbd|rgw)|radosgw|rbd-)")


def _update_rank(p):
    """What a person looks for first: the kernel, then Proxmox itself, and Ceph's many parts last."""
    n = p["name"]
    if p["origin"] != "Proxmox":
        return 5
    if KERNEL_PKG.match(n):
        return 0
    if n in HEADLINE_PKG:
        return 1
    if CEPH_PKG.match(n):
        return 4
    return 2 if n.startswith(("pve-", "proxmox-")) else 3


def summarize_updates(pkgs, checked=None):
    """What /nodes/{node}/apt/update lists, reduced to what the widget and the top bar show.
    `checked`: when the package lists were last refreshed (unix time), if known."""
    out = [{"name": p.get("Package", ""), "old": p.get("OldVersion", ""), "new": p.get("Version", ""),
            "origin": p.get("Origin", "")} for p in pkgs or []]
    out.sort(key=lambda p: (_update_rank(p), HEADLINE_PKG.index(p["name"]) if p["name"] in HEADLINE_PKG else 0, p["name"]))
    return {"allowed": True, "count": len(out),
            "proxmox": sum(p["origin"] == "Proxmox" for p in out),
            "kernel": any(KERNEL_PKG.match(p["name"]) for p in out),
            "checked": checked,
            "packages": out[:50]}


def last_apt_check(tasks):
    """When the package lists were last refreshed: the newest successful "aptupdate" task
    (Proxmox runs one every day by itself, and the Refresh button in its web UI runs another)."""
    done = [x.get("endtime") or x.get("starttime") or 0 for x in tasks or []
            if x.get("type") == "aptupdate" and x.get("status") == "OK"]
    return max(done) if done and max(done) else None


async def updates_summary(pve, t, node):
    pkgs, tasks = await asyncio.gather(pve.get(t, f"/nodes/{node}/apt/update"),
                                       pve.get(t, f"/nodes/{node}/tasks", typefilter="aptupdate", limit=10),
                                       return_exceptions=True)
    if isinstance(pkgs, BaseException):
        raise pkgs
    # the task list is a nicety: someone who may not read it still gets the packages
    return summarize_updates(pkgs, None if isinstance(tasks, BaseException) else last_apt_check(tasks))


async def may_update(req, s):
    pve, node = req.app["pve"], req.app["cfg"]["node"]
    return await pve.can(s["ticket"], f"/nodes/{node}", "Sys.Modify")


@routes.get("/api/node-updates")
async def node_updates(req):
    """Package updates waiting on this node, as Proxmox already knows them (its daily apt update);
    reading the list needs Sys.Modify on the node, like in the Proxmox web UI."""
    s = await session(req)
    if not await may_update(req, s):
        return web.json_response({"allowed": False})
    return web.json_response(await updates_summary(req.app["pve"], s["ticket"], req.app["cfg"]["node"]))


@routes.post("/api/node-updates/refresh")
async def node_updates_refresh(req):
    """Refresh the package lists now (apt-get update, run by Proxmox as a task) and answer with
    what is waiting then. Installing stays in Proxmox itself: Node → Updates → Upgrade."""
    s = await session(req)
    if not await may_update(req, s):
        raise PVEError(403, i18n._("forbidden"))
    pve, node, lock = req.app["pve"], req.app["cfg"]["node"], req.app["apt_lock"]
    # Two people pressing at once share one run: apt would refuse the second while the first holds its lock.
    if not lock.locked():
        async with lock:
            upid = await pve.post(s["ticket"], f"/nodes/{node}/apt/update")
            try:
                await pve.wait_task(s["ticket"], node, upid, timeout=180)
            except PVEError as e:
                raise PVEError(504, i18n._("apt_slow")) if e.status == 504 else \
                    PVEError(502, i18n._("apt_failed", err=str(e)))
    else:
        async with lock:
            pass
    return web.json_response(await updates_summary(pve, s["ticket"], node))


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
    s = await session(req)
    running = await req.app["running"]()
    seen = {vmid for (typ, vmid) in await visible_guests(req, s) if typ == "qemu"}
    out = []
    for g in await G.list_gpus(running):
        out.append({**g, "assigned_vms": [v for v in g["assigned_vms"] if v in seen],
                    "running_vm": g["running_vm"] if g["running_vm"] in seen else (0 if g["running_vm"] else None)})
    return web.json_response(out)


@routes.get("/api/systems")
async def systems(req):
    s = await session(req)
    seat = seat_of(req)
    L = req.app["launcher"]
    out = []
    seen = {vmid for (typ, vmid) in await visible_guests(req, s) if typ == "qemu"}
    for vm in await L.systems(s["ticket"]):
        out.append({**vm, "options": await L.options(seat, vm, seen)})
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
    resources = {}
    for k, lo, hi in (("memory", 512, 4 * 1024 * 1024), ("cores", 1, 512)):
        v = body.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise web.HTTPBadRequest(text=f"{k}: {lo}…{hi}")
        resources[k] = v
    job = await req.app["launcher"].launch(s["ticket"], seat_of(req), vmid_of(body.get("vmid")), body["gpu"], resources)
    req.app["resources"].invalidate()
    return web.json_response(job.as_dict())


@routes.get("/api/jobs/{id}")
async def job(req):
    s = await session(req)
    jid = req.match_info["id"]
    j = req.app["launcher"].jobs.get(int(jid)) if jid.isdigit() else None
    if not j or (j.owner and j.owner != s["user"]):
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


UPDATE_CHECK_GAP = 30   # s: GitHub limits how often a host may ask


# ---------------- Settings → System: the host's settings, changed in the menu ----------------
def _system_form(app):
    return {"groups": list(settings.GROUPS), "settings": settings.describe(config.load_file(), settings.load_overlay()),
            "restart": app["runtime"].get("restart"), "not_in_menu": sorted(settings.NOT_IN_MENU)}


def apply_settings(app, paths):
    """Settings that take effect at once: the running config gets the new values of `paths`
    (the rest of it, changed at run time, stays), and what was built from them is built again."""
    fresh = config.load()
    cfg = app["cfg"]
    for p in paths:
        v, there = settings._get(fresh, p)
        if there:
            settings._set(cfg, p, v)
    hosts = app["allowed_hosts_cache"]
    hosts.clear()
    hosts.update(allowed_hosts(app))
    if any(p.split(".")[0] in ("caddy", "discovery", "services", "links") for p in paths):
        app["services"].invalidate()
        if any(p.startswith("discovery") for p in paths):
            app["discovered"].invalidate()
    if any(p.startswith(("update.", "feedback.")) for p in paths):
        app["update"].invalidate()


@routes.get("/api/system/settings")
async def system_settings(req):
    s = await session(req)
    await require(req, s, "Sys.Modify")
    return web.json_response(_system_form(req.app))


@routes.put("/api/system/settings")
async def system_settings_put(req):
    """{"set": {path: value}, "reset": [path, ...]}: reset takes a setting back to config.yaml."""
    s = await session(req)
    await require(req, s, "Sys.Modify")
    try:
        body = await req.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("set", {}), dict) or not isinstance(body.get("reset", []), list):
        raise web.HTTPBadRequest(text='{"set": {...}, "reset": [...]} expected')
    sets, resets = body.get("set") or {}, [str(p) for p in body.get("reset") or []]
    _, errors = settings.change(sets, resets)
    if errors:
        return web.json_response({"error": "; ".join(errors.values()), "errors": errors}, status=400)
    paths = list(sets) + resets
    apply_settings(req.app, paths)
    need = settings.restart_needed(paths)
    if need:
        rt = req.app["runtime"]
        rt["restart"] = "all" if rt.get("restart") and rt["restart"] != need else need
    log.info("settings changed by %s: %s", s["user"], ", ".join(paths))
    return web.json_response(_system_form(req.app))


@routes.post("/api/system/restart")
async def system_restart(req):
    """Restart what the changed settings need: the backend, the kiosk screens, or both."""
    s = await session(req)
    await require(req, s, "Sys.Modify")
    what = req.app["runtime"].get("restart") or "backend"
    req.app["runtime"]["restart"] = None
    units = (["pve-homelab.service"] if what in ("backend", "all") else []) + (["pve-homelab-kiosk@*"] if what in ("kiosk", "all") else [])
    log.info("restart of %s asked by %s", ", ".join(units), s["user"])
    if not req.app.get("demo"):
        # its own unit: restarting the backend must not cut the command that does it
        await run("systemd-run", "--unit=pve-homelab-restart", "--collect", "--quiet", "systemctl", "restart", *units)
    return web.json_response({"restarting": what})


@routes.put("/api/update/auto")
async def update_auto(req):
    """Settings → About: install new releases by night (admins). Kept beside config.yaml, winning over its update.auto."""
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    try:
        on = (await req.json()).get("auto")
    except (ValueError, AttributeError):
        on = None
    if not isinstance(on, bool):
        raise web.HTTPBadRequest(text='{"auto": true | false} expected')
    update.set_auto(on)
    if req.app["update"].value:   # the held answer says what the switch is: keep it true at once
        req.app["update"].value = {**req.app["update"].value, "auto": on}
    log.info("automatic updates turned %s by %s", "on" if on else "off", s["user"])
    return web.json_response({"auto": on})


@routes.post("/api/update/check")
async def update_check(req):
    """Ask GitHub now instead of waiting for the next check (every update.check_hours), from
    Settings → About. Admins only; a check made less than 30 s ago is answered as it is."""
    s = await session(req)
    if not await req.app["pve"].can(s["ticket"], "/", "Sys.Modify"):
        raise PVEError(403, i18n._("forbidden"))
    cache, held = req.app["update"], req.app["update"].value
    try:
        recent = held and time.time() - held.get("checked", 0) < UPDATE_CHECK_GAP
        st = dict(held if recent else await cache.fresh())
    except Exception as e:
        return web.json_response({"enabled": False, "error": str(e)})
    st["can_apply"] = True
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
    if cfg["web"].get("enabled"):
        # a browser elsewhere, through the reverse proxy: no monitor, no GPU (see seat_of)
        cfg["seats"].setdefault("web", {"title": "Browser", "gpu": None, "kiosk": False, "remote": True})
    app["pve"] = PVE()
    app["stats"] = HostStats()
    app["ddc"] = DDC(cfg["monitors"])
    app["sessions"] = {}
    app["consoles"] = {}
    app["host_ip"] = _host_ip()
    app["allowed_hosts_cache"] = allowed_hosts(app)
    app["login_fails"] = {}
    app["tfa"] = {}   # id -> a sign-in waiting for its second factor
    app["runtime"] = {}   # what changes while the menu runs: a restart the settings are waiting for
    app["apt_lock"] = asyncio.Lock()
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

    app["known_ips"] = {}

    async def build_services():
        res = await app["resources"].get()
        live = await caddy.guest_ips(cfg["node"], res)
        # A stopped guest has no live address, and its Caddy site would belong to nobody (and be
        # shown to everyone): the address it last had, or a static one in its config, still says whose.
        app["known_ips"].update(live)
        ips = {**caddy.static_ips(res), **app["known_ips"], **live}
        listed = caddy.build(cfg, await caddy.routes(cfg), ips, app["host_ip"])
        try:
            found = await app["discovered"].get()
        except Exception as e:
            log.warning("discovery failed: %s", e)
            found = []
        return discover.merge(listed, discover.decorate(found, cfg.get("services")))
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
    """Watch VMs that already hold a GPU wired to a menu monitor (started before us); the watch
    loop keeps doing it for those started from Proxmox while the menu runs."""
    try:
        await app["launcher"].adopt()
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
    for cid in [k for k, v in app["tfa"].items() if now > v["until"]]:
        del app["tfa"][cid]


async def housekeeping_loop(app):
    while True:
        await asyncio.sleep(60)
        try:
            housekeeping(app)
        except Exception as e:
            log.warning("housekeeping: %s", e)


async def on_shutdown(app):
    app["stopping"].set()


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
    app = web.Application(middlewares=[gate, errors, guard, features])
    app.on_response_prepare.append(_no_stale_code)
    app["cfg"] = config.load()
    app["code"] = {k: update.installed()[k] for k in ("version", "commit")}  # what this process runs
    app["stopping"] = asyncio.Event()  # set on shutdown: long-lived streams (live reload) end at once
    app.add_routes(routes)
    app.router.add_static("/", config.WEB_DIR, show_index=False, append_version=False)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)
    return app
