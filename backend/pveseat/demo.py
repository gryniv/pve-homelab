"""Demo mode: the real app over a made-up Proxmox, runnable on any computer.

Started by demo.py in the repository root. Nothing here touches a real host:
Proxmox API, pvesh, sysfs GPUs, DDC, Caddy, host stats and updates are replaced by an
in-memory world. Any password works; starting/stopping guests changes that world only.
"""

import asyncio
import itertools
import logging
import math
import random
import time

from aiohttp import web

from . import app as A, caddy, gpus as G, i18n, launch as L, update, util, weather
from .ddc import DDC
from .pve import PVE, PVEError, Ticket

GB = 1024 ** 3
T0 = time.time()
NODE = "demo"

# vmid -> guest. "hostpci" lists GPUs passed through; "ip" is what Caddy proxies to.
WORLD = {
    100: dict(type="qemu", name="ubuntu-desktop", status="stopped", tags="seat", cores=8, mem=16, ostype="l26", vga="virtio"),
    101: dict(type="qemu", name="home-server", status="running", tags="", cores=4, mem=8, ostype="l26", vga="std", ip="10.0.0.101"),
    102: dict(type="qemu", name="win11-gaming", status="stopped", tags="seat", cores=12, mem=32, ostype="win11", vga="std", hostpci=["0000:01:00"]),
    103: dict(type="qemu", name="fedora-workstation", status="stopped", tags="seat", cores=8, mem=12, ostype="l26", vga="virtio"),
    200: dict(type="lxc", name="caddy", status="running", cores=1, mem=0.5, ip="10.0.0.200"),
    201: dict(type="lxc", name="jellyfin", status="running", cores=4, mem=4, ip="10.0.0.201"),
    202: dict(type="lxc", name="immich", status="running", cores=4, mem=6, ip="10.0.0.202"),
    203: dict(type="lxc", name="nextcloud", status="stopped", cores=2, mem=4, ip="10.0.0.203"),
    204: dict(type="lxc", name="vaultwarden", status="running", cores=1, mem=0.5, ip="10.0.0.204"),
    205: dict(type="lxc", name="home-assistant", status="running", cores=2, mem=2, ip="10.0.0.205"),
    206: dict(type="lxc", name="adguard", status="running", cores=1, mem=0.5, ip="10.0.0.206"),
}
for g in WORLD.values():
    g.setdefault("hostpci", [])
    g["started"] = T0 - random.randint(3600, 9 * 86400) if g["status"] == "running" else None

ROUTES = [("jellyfin", 201, 8096), ("photos", 202, 2283), ("cloud", 203, 80), ("vault", 204, 8080),
          ("home", 205, 8123), ("dns", 206, 3000), ("git", 101, 3000)]

USERS = [
    {"id": "ihor@pve", "first": "Ihor"},
    {"id": "guest@pve", "first": "Guest"},
    {"id": "root@pam", "first": ""},
]
GUEST_SEES = {100, 201, 202}   # guest@pve's permissions: one VM and two media services

GPUS = {
    "0000:00:02.0": dict(name="UHD Graphics 770", vendor="intel", driver="i915", integrated=True, boot_vga=True,
                         connectors=[{"name": "HDMI-A-1", "connected": True,
                                      "monitor": {"vendor": "DEL", "name": "DELL U2723QE", "serial": "DEMO123"}}]),
    "0000:01:00.0": dict(name="RTX 4070", vendor="nvidia", driver="vfio-pci", integrated=False, boot_vga=False,
                         connectors=[{"name": "DP-1", "connected": False, "monitor": None}]),
}

_upid = itertools.count(1)
log = logging.getLogger("pveseat.demo")


def _uptime(g):
    return int(time.time() - g["started"]) if g["started"] else 0


def _visible(user):
    return set(WORLD) if user != "guest@pve" else GUEST_SEES


def resources(user="root@pam"):
    out = []
    for vmid, g in WORLD.items():
        if vmid not in _visible(user):
            continue
        run = g["status"] == "running"
        wobble = (math.sin(time.time() / 30 + vmid) + 1) / 2
        out.append({
            "vmid": vmid, "type": g["type"], "name": g["name"], "status": g["status"], "tags": g.get("tags", ""),
            "maxcpu": g["cores"], "cpu": (0.02 + 0.2 * wobble) if run else 0,
            "maxmem": int(g["mem"] * GB), "mem": int(g["mem"] * GB * (0.3 + 0.4 * wobble)) if run else 0,
            "uptime": _uptime(g), "template": 0, "node": NODE,
        })
    return out


def qemu_config(vmid):
    g = WORLD[vmid]
    conf = {"name": g["name"], "ostype": g["ostype"], "cores": g["cores"], "sockets": 1,
            "memory": str(int(g["mem"] * 1024)), "vga": g["vga"], "tags": g.get("tags", "")}
    for i, dev in enumerate(g["hostpci"]):
        conf[f"hostpci{i}"] = f"{dev},pcie=1"
    return conf


class DemoPVE(PVE):
    async def login(self, username, password):
        if not username:
            raise PVEError(401, i18n._("bad_login"))
        return Ticket(username, "demo", "demo")

    async def renew(self, t):
        return t

    async def get(self, t, endpoint, **params):
        await asyncio.sleep(0.05)
        if endpoint == "/cluster/resources":
            return resources(t.user)
        if endpoint.startswith(f"/nodes/{NODE}/qemu/") and endpoint.endswith("/config"):
            return qemu_config(int(endpoint.split("/")[4]))
        if endpoint == f"/nodes/{NODE}/storage":
            return [{"storage": "local", "type": "dir", "active": 1, "used": 38 * GB, "total": 94 * GB},
                    {"storage": "local-zfs", "type": "zfspool", "active": 1, "used": 612 * GB, "total": 1800 * GB},
                    {"storage": "media", "type": "dir", "active": 1, "used": 7400 * GB, "total": 12000 * GB}]
        if endpoint == "/access/permissions":
            path = params["path"]
            return {path: {p: 1 for p in self._privs(t.user, path)}}
        if "/tasks/" in endpoint:
            return {"status": "stopped", "exitstatus": "OK"}
        raise PVEError(404, endpoint)

    @staticmethod
    def _privs(user, path):
        if user != "guest@pve":
            return ["VM.PowerMgmt", "VM.Config.HWType", "Sys.Modify", "Sys.PowerMgmt"]
        if path.startswith("/vms/") and int(path.split("/")[2]) in GUEST_SEES:
            return ["VM.PowerMgmt"]
        return []

    async def post(self, t, endpoint, **data):
        parts = endpoint.strip("/").split("/")
        if len(parts) == 6 and parts[4] == "status":
            vmid, action = int(parts[3]), parts[5]
            if vmid not in _visible(t.user) or "VM.PowerMgmt" not in self._privs(t.user, f"/vms/{vmid}"):
                raise PVEError(403, i18n._("forbidden"))
            g = WORLD[vmid]
            if action == "start":
                g["status"], g["started"] = "running", time.time()
            elif action in ("stop", "shutdown"):
                g["status"], g["started"] = "stopped", None
            elif action == "reboot":
                g["started"] = time.time()
            A_app["resources"].invalidate()
            log.info("demo: %s %s by %s", action, g["name"], t.user)
            return f"UPID:{NODE}:{next(_upid)}"
        if endpoint.endswith("/vncproxy"):
            raise PVEError(501, i18n._("demo_console"))
        raise PVEError(501, i18n._("demo_action"))

    async def wait_task(self, *a, **k):
        await asyncio.sleep(1.2)

    async def can(self, t, path, priv):
        return priv in self._privs(t.user, path)


class DemoStats:
    def __init__(self, *_a):
        self.cpu, self.hist = 12.0, []

    async def loop(self):
        n = 0
        while True:
            self.cpu = max(3, min(92, self.cpu + random.uniform(-4, 4.5)))
            if n % 4 == 0:
                self.hist = (self.hist + [round(self.cpu, 1)])[-90:]
            n += 1
            await asyncio.sleep(5)

    def snapshot(self):
        running = sum(g["status"] == "running" for g in WORLD.values())
        return {"cpu": round(self.cpu, 1), "cpu_hist": self.hist, "cores": 16,
                "mem_total": 64 * GB, "mem_used": int((10 + 3.2 * running) * GB),
                "temp": int(46 + self.cpu / 4), "uptime": int(time.time() - T0 + 3 * 86400 + 4 * 3600),
                "net_rx_mbit": round(random.uniform(2, 60), 1), "net_tx_mbit": round(random.uniform(0.5, 9), 1),
                "load": round(self.cpu / 20, 2)}


async def demo_gpus(running):
    out = []
    for pci, d in GPUS.items():
        vms = [vmid for vmid, g in WORLD.items() if any(G.gpu_of(x) == pci for x in g["hostpci"])]
        out.append({"pci": pci, **d, "assigned_vms": vms,
                    "running_vm": next((v for v in vms if v in running), None)})
    return out


async def demo_pvesh(path, **params):
    if path == "/cluster/resources":
        return resources()
    if path == "/version":
        return {"version": "9.2-demo"}
    return []


async def demo_routes(cfg):
    return [{"key": k, "host": f"{k}.home.example", "upstream": f"{WORLD[vmid]['ip']}:{port}"} for k, vmid, port in ROUTES] + \
           [{"key": "pve", "host": "pve.home.example", "upstream": f"{A._host_ip()}:8006"}]


async def demo_ips(node, res):
    return {g["ip"]: (g["type"], vmid, g["name"]) for vmid, g in WORLD.items() if g.get("ip") and g["status"] == "running"}


async def assign_gpu(self, vmid, gpu):
    WORLD[vmid]["hostpci"] = [gpu.rsplit(".", 1)[0]]
    log.info("demo: %s now owns %s", WORLD[vmid]["name"], gpu)


async def to_virgl(self, vmid):
    WORLD[vmid].update(vga="virtio-gl", hostpci=[])
    log.info("demo: %s switched to VirGL", WORLD[vmid]["name"])


async def switch_input(self, mon, pci):
    log.info("demo: monitor %s -> %s (DDC skipped)", mon, pci)
    return True


_real_weather = weather.get


async def demo_weather(city, units="c"):
    try:
        return await asyncio.wait_for(_real_weather(city, units), 6)
    except Exception:
        return {"city": city, "units": units, "kind": "partly", "temp": 14, "wind": 3, "humidity": 64, "is_day": True,
                "days": [{"date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * i)),
                          "kind": k, "max": 16 - i, "min": 7 - i} for i, k in enumerate(["clear", "rain", "overcast"], 1)]}


async def demo_update_status(cfg):
    cur = update.installed()
    return {"enabled": True, "repo": "example/pve-seat", "channel": "release", "auto": False, "installed": cur,
            "available": True, "checked": int(time.time()),
            "latest": {"ref": "v9.9.0", "version": "9.9.0", "commit": None, "url": "https://github.com/", "notes": "Demo release"}}


async def demo_run(*args, **kw):
    log.info("demo: would run %s", " ".join(args))
    return ""


def demo_users(app):
    from . import prefs
    out = []
    for u in USERS:
        pr = prefs.load(u["id"])
        out.append({"id": u["id"], "name": u["first"] or u["id"].split("@")[0], "full": u["first"],
                    "avatar": pr["avatar"] if u["id"] != "guest@pve" or pr["avatar"] else 1, "skin": pr["skin"],
                    "background": pr["background"], "login": pr["layout"].get("login", []), "lang": pr["lang"]})
    return out


A_app = {}


def make_app():
    i18n.MESSAGES["en"].update(demo_console="The VM screen isn't available in the demo",
                               demo_action="Not available in the demo")
    i18n.MESSAGES["uk"].update(demo_console="У демо екран VM недоступний", demo_action="У демо це недоступно")
    A.PVE = DemoPVE
    A.HostStats = DemoStats
    A.pvesh = util.pvesh = demo_pvesh
    A.pve_users = demo_users
    A.run = demo_run
    G.list_gpus = demo_gpus
    G.pretty_name = lambda pci, _n=GPUS: asyncio.sleep(0, (_n.get(pci) or {}).get("name", pci))
    caddy.routes = demo_routes
    caddy.guest_ips = demo_ips
    L.Launcher._assign_gpu = assign_gpu
    L.Launcher._to_virgl = to_virgl
    DDC.switch_to_gpu = switch_input
    weather.get = demo_weather
    update.status = demo_update_status
    app = A.make_app()
    app["demo"] = True

    async def remember(app):
        A_app["resources"] = app["resources"]
    app.on_startup.append(remember)
    return app


def run(host="127.0.0.1", port=8900):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    web.run_app(make_app(), host=host, port=port, print=None, access_log=None)
