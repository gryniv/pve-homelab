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

from . import app as A, caddy, discover, gpus as G, i18n, launch as L, update, util, weather, wol
from .ddc import DDC
from .pve import PVE, PVEError, TfaChallenge, Ticket

GB = 1024 ** 3
T0 = time.time()
NODE = "demo"

# vmid -> guest. "hostpci" is {slot: value} as in a VM config (hostpci0: ...); "ip" is what Caddy proxies to.
WORLD = {
    100: dict(type="qemu", name="ubuntu-desktop", status="stopped", tags="seat", cores=8, mem=16, ostype="l26", vga="virtio"),
    101: dict(type="qemu", name="home-server", status="running", tags="", cores=4, mem=8, ostype="l26", vga="std", ip="10.0.0.101"),
    102: dict(type="qemu", name="win11-gaming", status="stopped", tags="seat", cores=12, mem=32, ostype="win11", vga="std", hostpci={0: "mapping=rtx,pcie=1,x-vga=1"}),
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
    g.setdefault("hostpci", {})
    g["started"] = T0 - random.randint(3600, 9 * 86400) if g["status"] == "running" else None

# A PVE resource mapping for the RTX (/etc/pve/mapping/pci.cfg), as VM 102 uses it.
MAPPINGS = {"rtx": [{"node": NODE, "path": "0000:01:00"}]}


def devices(g):
    """The PCI devices a guest passes through, mappings resolved."""
    return [d for v in g["hostpci"].values() for d in G.hostpci_devices(v, NODE, MAPPINGS)]


# What "Caddy" proxies. AdGuard, Forgejo and Grafana are left out on purpose: the demo finds
# them the other ways (an open port in CT 206 / VM 101, a link in VM 101's notes).
ROUTES = [("jellyfin", 201, 8096), ("photos", 202, 2283), ("cloud", 203, 80), ("vault", 204, 8080),
          ("home", 205, 8123)]
DISCOVERED = [(206, 3000, "AdGuard Home", "adguard-home", "port"), (101, 3000, "Forgejo", "forgejo", "port"),
              (101, 3001, "Grafana", "grafana", "notes")]

USERS = [
    {"id": "ihor@pve", "first": "Ihor"},
    {"id": "guest@pve", "first": "Guest"},
    {"id": "olena@pve", "first": "Olena"},   # signs in with a code too (TFA_USERS)
    {"id": "root@pam", "first": ""},
]
APT_UPDATES = [
    {"Package": "pve-manager", "OldVersion": "9.2.1", "Version": "9.2.3", "Origin": "Proxmox"},
    {"Package": "proxmox-kernel-6.17.4-2-pve-signed", "OldVersion": "", "Version": "6.17.4-2", "Origin": "Proxmox"},
    {"Package": "qemu-server", "OldVersion": "9.1.4", "Version": "9.1.6", "Origin": "Proxmox"},
    {"Package": "openssl", "OldVersion": "3.5.1-1", "Version": "3.5.1-1+deb13u1", "Origin": "Debian"},
    {"Package": "libssl3t64", "OldVersion": "3.5.1-1", "Version": "3.5.1-1+deb13u1", "Origin": "Debian"},
    {"Package": "tzdata", "OldVersion": "2025b-4", "Version": "2025c-0+deb13u1", "Origin": "Debian"},
]
DISKS = [
    {"devpath": "/dev/nvme0n1", "model": "Samsung SSD 990 PRO 2TB", "type": "nvme", "size": 2000 * GB, "health": "PASSED", "wearout": 98},
    {"devpath": "/dev/nvme1n1", "model": "Samsung SSD 990 PRO 2TB", "type": "nvme", "size": 2000 * GB, "health": "PASSED", "wearout": 97},
    {"devpath": "/dev/sda", "model": "WDC WD120EFBX", "type": "hdd", "size": 12000 * GB, "health": "PASSED", "wearout": "N/A"},
]
POOLS = [{"name": "nvme2tb", "health": "ONLINE", "size": 1800 * GB, "alloc": 612 * GB}]
SNAPSHOTS = {  # vmid -> [(name, days ago, description, with RAM)]
    100: [("clean-install", 40, "Fresh Ubuntu, drivers in", False), ("before-upgrade", 3, "Before 26.04 upgrade", True)],
    201: [("pre-update", 9, "Jellyfin 10.10 before update", False)],
}
BACKUP_AGE = {100: 0.5, 101: 1, 102: 12, 200: 0.5, 201: 0.5, 202: 2, 205: 0.5, 206: 0.5}  # days since the last backup
GUEST_SEES = {100, 201, 202}   # guest@pve's permissions: one VM and two media services

GPUS = {
    "0000:00:02.0": dict(name="UHD Graphics 770", vendor="intel", driver="i915", integrated=True, boot_vga=True,
                         connectors=[{"name": "HDMI-A-1", "connected": True,
                                      "monitor": {"vendor": "DEL", "name": "DELL U2723QE", "serial": "DEMO123"}}]),
    "0000:01:00.0": dict(name="RTX 4070", vendor="nvidia", driver="vfio-pci", integrated=False, boot_vga=False,
                         connectors=[{"name": "DP-1", "connected": False, "monitor": None}]),
}

_upid = itertools.count(1)
log = logging.getLogger("pvehomelab.demo")


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


def rrddata(user, vmid, timeframe):
    """Made-up history: 70 points like Proxmox gives, gaps while the guest was off."""
    if vmid not in WORLD or vmid not in _visible(user):
        raise PVEError(403, i18n._("forbidden"))
    g = WORLD[vmid]
    step = {"hour": 60, "day": 1200, "week": 8640}[timeframe]
    now = int(time.time()) // step * step
    out = []
    for i in range(70):
        t = now - (69 - i) * step
        row = {"time": t}
        # a stopped guest shows its last hour of activity before it went down, then a gap
        on = g["status"] == "running" or i < 40
        if on:
            w = (math.sin(t / (step * 7) + vmid) + 1) / 2
            row.update(cpu=0.03 + 0.35 * w * w, maxcpu=g["cores"], mem=g["mem"] * GB * (0.35 + 0.3 * w),
                       maxmem=g["mem"] * GB, netin=2e5 + 3e6 * w, netout=1e5 + 1.2e6 * (1 - w),
                       diskread=5e4 * w, diskwrite=2e5 * (1 - w))
        out.append(row)
    return out


def qemu_config(vmid):
    g = WORLD[vmid]
    conf = {"name": g["name"], "ostype": g.get("ostype", "l26"), "cores": g["cores"], "sockets": 1,
            "memory": str(int(g["mem"] * 1024)), "vga": g.get("vga", "std"), "tags": g.get("tags", "")}
    for k in ("onboot", "startup", "description", "balloon", "swap"):
        if g.get(k) not in (None, ""):
            conf[k] = g[k]
    conf.update({f"hostpci{n}": v for n, v in g["hostpci"].items()})
    return conf


# Sign-ins with a second factor: the code and the recovery key that let these users in.
TFA_USERS = {"olena@pve": {"totp": "123456", "recovery": "demo-1111-2222"}}


CONFIG_PRIVS = {"memory": "VM.Config.Memory", "cores": "VM.Config.CPU", "balloon": "VM.Config.Memory",
                "swap": "VM.Config.Memory", "onboot": "VM.Config.Options", "startup": "VM.Config.Options",
                "tags": "VM.Config.Options", "description": "VM.Config.Options"}


class DemoPVE(PVE):
    async def req(self, t, method, path, data=None):
        """PUT /nodes/<node>/<type>/<id>/config, as Proxmox would: each field needs its privilege;
        a running VM keeps memory and cores pending, a container takes them at once."""
        parts = path.strip("/").split("/")
        if method != "PUT" or len(parts) != 5 or parts[4] != "config":
            return await super().req(t, method, path, data)
        vmid = int(parts[3])
        g = WORLD.get(vmid)
        if not g or vmid not in _visible(t.user):
            raise PVEError(403, i18n._("forbidden"))
        data = dict(data or {})
        fields = [k for k in data if k != "delete"] + [k for k in (data.get("delete") or "").split(",") if k]
        if any(CONFIG_PRIVS.get(k, "VM.Config.Options") not in self._privs(t.user, f"/vms/{vmid}") for k in fields):
            raise PVEError(403, i18n._("forbidden"))
        for k in (data.get("delete") or "").split(","):
            if k:
                g.pop(k, None)
        for k, v in data.items():
            if k == "delete":
                continue
            if g["type"] == "qemu" and g["status"] == "running" and k in ("memory", "cores"):
                g.setdefault("pending", {})[k] = v
            elif k == "memory":
                g["mem"] = int(v) / 1024
            elif k == "cores":
                g["cores"] = int(v)
            else:
                g[k] = v
        A_app["resources"].invalidate()
        return None

    async def login(self, username, password):
        if not username:
            raise PVEError(401, i18n._("bad_login"))
        if username in TFA_USERS:
            return TfaChallenge(username, f"PVE:{username}:!tfa!%7B%22totp%22%3Atrue%2C%22recovery%22%3A%22available%22%7D:0::demo",
                                ["totp", "recovery"])
        return Ticket(username, "demo", "demo")

    async def finish_tfa(self, ch, kind, code):
        if TFA_USERS.get(ch.user, {}).get(kind) != code:
            raise PVEError(401, i18n._("bad_tfa"))
        return Ticket(ch.user, "demo", "demo")

    async def renew(self, t):
        return t

    async def get(self, t, endpoint, **params):
        await asyncio.sleep(0.05)
        if endpoint == "/cluster/resources":
            return resources(t.user)
        if endpoint.endswith("/snapshot"):
            vmid = int(endpoint.split("/")[4])
            if vmid not in _visible(t.user):
                raise PVEError(403, i18n._("forbidden"))
            now = int(time.time())
            return [{"name": n, "snaptime": now - age * 86400, "description": d, **({"vmstate": 1} if ram else {})}
                    for n, age, d, ram in SNAPSHOTS.get(vmid, [])] + [{"name": "current", "running": 1}]
        if endpoint.endswith("/rrddata"):
            return rrddata(t.user, int(endpoint.split("/")[4]), params.get("timeframe", "hour"))
        if endpoint.startswith((f"/nodes/{NODE}/qemu/", f"/nodes/{NODE}/lxc/")) and endpoint.endswith("/config"):
            vmid = int(endpoint.split("/")[4])
            if vmid not in _visible(t.user):
                raise PVEError(403, i18n._("forbidden"))
            return qemu_config(vmid)
        if endpoint.endswith("/pending"):
            return [{"key": k, "value": v, "pending": v} for k, v in WORLD[int(endpoint.split("/")[4])].get("pending", {}).items()]
        if endpoint == f"/nodes/{NODE}/storage" and params.get("content") == "backup":
            return [{"storage": "pbs", "type": "pbs", "active": 1, "content": "backup"}]
        if endpoint == f"/nodes/{NODE}/storage/pbs/content":
            now = time.time()
            return [{"volid": f"pbs:backup/{vmid}/{i}", "vmid": vmid, "ctime": int(now - age * 86400 - i * 7 * 86400),
                     "size": 8 * GB, "content": "backup"}
                    for vmid, age in BACKUP_AGE.items() for i in range(3)]
        if endpoint == f"/nodes/{NODE}/storage":
            return [{"storage": "local", "type": "dir", "active": 1, "used": 38 * GB, "total": 94 * GB},
                    {"storage": "local-zfs", "type": "zfspool", "active": 1, "used": 612 * GB, "total": 1800 * GB},
                    {"storage": "media", "type": "dir", "active": 1, "used": 7400 * GB, "total": 12000 * GB}]
        if endpoint == f"/nodes/{NODE}/disks/list":
            return DISKS
        if endpoint == f"/nodes/{NODE}/disks/zfs":
            return POOLS
        if endpoint == f"/nodes/{NODE}/apt/update":
            return APT_UPDATES
        if endpoint == f"/nodes/{NODE}/tasks":
            end = int(STATE["apt_checked"])
            return [{"type": "aptupdate", "status": "OK", "user": "root@pam", "starttime": end - 9, "endtime": end}
                    ] if params.get("typefilter") in (None, "aptupdate") else []
        if endpoint == "/access/permissions":
            path = params["path"]
            return {path: {p: 1 for p in self._privs(t.user, path)}}
        if "/tasks/" in endpoint:
            return {"status": "stopped", "exitstatus": "OK"}
        raise PVEError(404, endpoint)

    @staticmethod
    def _privs(user, path):
        if user != "guest@pve":
            return ["VM.PowerMgmt", "VM.Config.HWType", "Sys.Audit", "Sys.Modify", "Sys.PowerMgmt", "Mapping.Use",
                    "VM.Config.Memory", "VM.Config.CPU", "VM.Config.Options", "VM.Console"]
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
                if STATE.get("fail") == "start":  # tests: a start that Proxmox refuses
                    raise PVEError(500, "start failed (demo)")
                g["status"], g["started"] = "running", time.time()
            elif action in ("stop", "shutdown"):
                g["status"], g["started"] = "stopped", None
                for k, v in g.pop("pending", {}).items():   # what waited for the next start is the config now
                    g["mem" if k == "memory" else k] = int(v) / 1024 if k == "memory" else int(v)
            elif action == "reboot":
                g["started"] = time.time()
            A_app["resources"].invalidate()
            log.info("demo: %s %s by %s", action, g["name"], t.user)
            return f"UPID:{NODE}:{next(_upid)}"
        if endpoint.endswith("/vncproxy"):
            raise PVEError(501, i18n._("demo_console"))
        if endpoint == f"/nodes/{NODE}/apt/update":   # the package lists, refreshed by hand
            if "Sys.Modify" not in self._privs(t.user, f"/nodes/{NODE}"):
                raise PVEError(403, i18n._("forbidden"))
            STATE["apt_checked"] = time.time() + 1.2
            return f"UPID:{NODE}:{next(_upid)}:aptupdate"
        raise PVEError(501, i18n._("demo_action"))

    async def wait_task(self, t, node, upid, timeout=120):
        await asyncio.sleep(1.2)
        if "aptupdate" in upid and STATE.get("fail") == "apt":   # tests: a repository that answers 401
            raise PVEError(500, "command 'apt-get update' failed: exit code 100")

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
        vms = [vmid for vmid, g in WORLD.items() if any(G.gpu_of(x) == pci for x in devices(g))]
        out.append({"pci": pci, **d, "assigned_vms": vms,
                    "running_vm": next((v for v in vms if v in running), None)})
    return out


async def demo_pvesh(path, /, **params):
    if path == "/cluster/resources":
        return resources()
    if path == "/version":
        return {"version": "9.2-demo"}
    return []


async def demo_routes(cfg):
    return [{"key": k, "host": f"{k}.home.example", "upstream": f"{WORLD[vmid]['ip']}:{port}"} for k, vmid, port in ROUTES] + \
           [{"key": "pve", "host": "pve.home.example", "upstream": f"{A._host_ip()}:8006"}]


def demo_static_ips(res, read=None):
    return {g["ip"]: (g["type"], vmid, g["name"]) for vmid, g in WORLD.items() if g.get("ip")}


async def demo_ips(node, res):
    return {g["ip"]: (g["type"], vmid, g["name"]) for vmid, g in WORLD.items() if g.get("ip") and g["status"] == "running"}


async def demo_discover(cfg, res, ips, host_ip=None):
    out = []
    for vmid, port, name, icon, source in DISCOVERED:
        g = WORLD[vmid]
        if g["status"] != "running":
            continue
        out.append({"key": f"{'ct' if g['type'] == 'lxc' else 'vm'}{vmid}-{port}", "name": name, "icon": icon, "desc": name,
                    "url": f"http://{g['ip']}:{port}", "host": f"{g['ip']}:{port}", "upstream": f"{g['ip']}:{port}",
                    "guest": {"type": g["type"], "vmid": vmid, "name": g["name"]}, "source": source, "port": port})
    return out


# The input devices of the demo host (/proc/bus/input/devices): a wireless receiver with a keyboard
# and a mouse, an Xbox pad, a Bluetooth keyboard, and the keyboard VM 102 has of its own (usb0).
INPUT_DEVICES = """I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name="Logitech USB Receiver"
P: Phys=usb-0000:00:14.0-3/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3:1.0/0003:046D:C52B.0001/input/input5
H: Handlers=sysrq kbd leds event5
B: EV=120013

I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name="Logitech USB Receiver Mouse"
P: Phys=usb-0000:00:14.0-3/input1
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3:1.1/0003:046D:C52B.0002/input/input6
H: Handlers=mouse0 event6
B: EV=17

I: Bus=0003 Vendor=045e Product=0b12 Version=0509
N: Name="Microsoft Xbox Controller"
P: Phys=usb-0000:00:14.0-4/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4:1.0/input/input7
H: Handlers=event7 js0
B: EV=20000b

I: Bus=0005 Vendor=05ac Product=024f Version=0011
N: Name="Keychron K2"
P: Phys=
S: Sysfs=/devices/virtual/misc/uhid/0005:05AC:024F.0004/input/input9
H: Handlers=sysrq kbd leds event9
B: EV=120013

I: Bus=0003 Vendor=046d Product=c534 Version=0111
N: Name="Logitech K270"
P: Phys=usb-0000:00:14.0-5/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-5/1-5:1.0/0003:046D:C534.0005/input/input11
H: Handlers=sysrq kbd leds event11
B: EV=120013

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
P: Phys=PNP0C0C/button/input0
S: Sysfs=/devices/LNXSYSTM:00/input/input0
H: Handlers=kbd event0
B: EV=3
"""
INPUT_LINKS = {"event5": "/dev/input/by-id/usb-Logitech_USB_Receiver-event-kbd",
               "event6": "/dev/input/by-id/usb-Logitech_USB_Receiver-if01-event-mouse",
               "event7": "/dev/input/by-id/usb-Microsoft_Controller-event-joystick"}
QEMU_LOG = []      # (vmid, command) sent to QEMU's monitor
GRABBED = set()    # evdev nodes QEMU holds


def demo_units(node):
    from . import inputs
    return inputs.units(inputs.parse_devices(INPUT_DEVICES), INPUT_LINKS, {102: "usb0: host=046d:c534\n"}, NODE, {})


async def demo_monitor(node, vmid, command):
    QEMU_LOG.append((vmid, command))
    if command.startswith("object_add input-linux") and "grab-toggle" in command:
        GRABBED.add(command.split("evdev=", 1)[1].split(",")[0])
    if command.startswith("object_del"):
        GRABBED.clear()
    return ""


WOKEN = []


def demo_wake(target):
    WOKEN.append(target["name"])
    log.info("demo: magic packet for %s (%s) not sent", target["name"], target["mac"])


async def switch_input(self, mon, pci):
    log.info("demo: monitor %s -> %s (DDC skipped)", mon, pci)
    return True


async def demo_power(self, mon, on):
    log.info("demo: monitor %s %s (DDC skipped)", mon, "on" if on else "dark")
    return True


_real_weather = weather.get


async def demo_weather(city, units="c"):
    if STATE["weather"]:
        k = STATE["weather"]
        temp = {"snow": -4, "thunder": 19, "clear": 22, "fog": 7}.get(k, 12)
        return {"city": city, "units": units, "kind": k, "temp": temp, "wind": 5, "humidity": 80, "is_day": True,
                "days": [{"date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * i)),
                          "kind": k, "max": temp + 2, "min": temp - 5} for i in (1, 2, 3)]}
    try:
        return await asyncio.wait_for(_real_weather(city, units), 6)
    except Exception:
        return {"city": city, "units": units, "kind": "partly", "temp": 14, "wind": 3, "humidity": 64, "is_day": True,
                "days": [{"date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * i)),
                          "kind": k, "max": 16 - i, "min": 7 - i} for i, k in enumerate(["clear", "rain", "overcast"], 1)]}


async def demo_update_status(cfg):
    cur = update.installed()
    return {"enabled": True, "repo": "example/pve-homelab", "channel": "release", "auto": update.settings(cfg)["auto"], "installed": cur,
            "available": STATE["update"], "checked": int(time.time()),
            "latest": {"ref": "v9.9.0", "version": "9.9.0", "commit": None, "url": "https://github.com/", "notes": "Demo release"}}


def fake_qm(args):
    """`qm config <id>` and `qm set <id> ...` over the demo world, so the launcher's own planning
    (hostpci slots, mappings, VirGL and back) runs in the demo and the tests as it does on a host."""
    vmid = int(args[2])
    g = WORLD[vmid]
    if args[1] == "config":
        lines = [f"name: {g['name']}", f"vga: {g['vga']}"] + [f"hostpci{n}: {v}" for n, v in sorted(g["hostpci"].items())]
        return "\n".join(lines) + "\n"
    it = iter(args[3:])
    for opt in it:
        val = next(it)
        if opt == "--delete":
            for k in val.split(","):
                if k.startswith("hostpci"):
                    g["hostpci"].pop(int(k[7:]), None)
                elif k == "vga":
                    g["vga"] = "std"   # Proxmox's default
        elif opt.startswith("--hostpci"):
            g["hostpci"][int(opt[9:])] = val
        elif opt == "--vga":
            g["vga"] = val
    log.info("demo: %s", " ".join(args))
    return ""


async def demo_run(*args, **kw):
    if args[:1] == ("qm",) and len(args) > 2 and args[1] in ("config", "set"):
        return fake_qm(args)
    log.info("demo: would run %s", " ".join(args))
    return ""


def demo_users(app):
    from . import prefs
    out = []
    for u in USERS:
        pr = prefs.load(u["id"])
        pub = prefs.public(pr)
        if u["id"] == "guest@pve" and not pr["avatar"]:
            pub["avatar"] = 1
        out.append({"id": u["id"], "name": u["first"] or u["id"].split("@")[0], "full": u["first"], **pub})
    return out


A_app = {}

# ---------------------------------------------------------------- demo panel
# The menu's demo panel adds systems and services to the in-memory world, changes the
# weather and pretends an update exists. Everything added is marked so it can be removed.
APT_CHECKED = T0 - 5 * 3600   # Proxmox's own daily refresh of the package lists, a few hours ago
STATE = {"weather": "", "update": True, "added": [], "apt_checked": APT_CHECKED}
_initial = None
OS_TYPES = {"windows": ("win11", "Windows"), "ubuntu": ("l26", "Ubuntu"), "fedora": ("l26", "Fedora"),
            "debian": ("l26", "Debian"), "macos": ("other", "macOS"), "linux": ("l26", "Linux")}
APP_PORTS = {"jellyfin": 8096, "plex": 32400, "immich": 2283, "nextcloud": 80, "vaultwarden": 8080,
             "home-assistant": 8123, "adguard-home": 3000, "grafana": 3000, "uptime-kuma": 3001, "portainer": 9443,
             "paperless-ngx": 8000, "audiobookshelf": 13378, "syncthing": 8384, "n8n": 5678}


def _snapshot():
    import copy
    return copy.deepcopy((WORLD, ROUTES, DISCOVERED))


def _slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "app"


def _free_id(start, stop):
    return next(i for i in range(start, stop) if i not in WORLD)


async def _refresh():
    """Recompute right away so the next dashboard refresh already shows the change."""
    for k in ("resources", "discovered", "services", "update"):
        if k in A_app:
            A_app[k].invalidate()
            await A_app[k]._refresh()


async def _json(req):
    try:
        return await req.json()
    except Exception:
        return {}


@A.routes.get("/api/demo/state")
async def demo_state(req):
    added = [{"id": vmid, "type": WORLD[vmid]["type"], "name": WORLD[vmid]["name"],
              "what": WORLD[vmid].get("demo_what", "")} for vmid in STATE["added"] if vmid in WORLD]
    return web.json_response({"weather": STATE["weather"], "update": STATE["update"], "added": added,
                              "os": list(OS_TYPES), "apps": sorted(APP_PORTS)})


@A.routes.post("/api/demo/wol-packet")
async def demo_wol_packet(req):
    """A Wake-on-LAN packet for a MAC address, as Moonlight would send it."""
    b = await _json(req)
    mac = bytes.fromhex(str(b.get("mac", "")).replace(":", ""))
    vmid = await A_app["app"]["wolserver"].packet(b"\xff" * 6 + mac * 16, b.get("from") or "192.168.8.20")
    return web.json_response({"started": vmid})


@A.routes.post("/api/demo/screen-off")
async def demo_screen_off(req):
    """As if the screen had been idle long enough: the monitor goes dark."""
    await A_app["app"]["power"]._set(A.seat_of(req), False)
    return web.json_response({"ok": True})


@A.routes.post("/api/demo/input-release")
async def demo_input_release(req):
    """As if both Ctrl were pressed inside the system: QEMU lets the keyboard go."""
    GRABBED.clear()
    return web.json_response({"ok": True})


@A.routes.post("/api/demo/vm")
async def demo_add_vm(req):
    b = await _json(req)
    os_key = b.get("os") if b.get("os") in OS_TYPES else "linux"
    vmid = _free_id(104, 200)
    WORLD[vmid] = dict(type="qemu", name=_slug(b.get("name") or f"{os_key}-{vmid}"), status="running" if b.get("running") else "stopped",
                       tags="seat", cores=int(b.get("cores") or 4), mem=float(b.get("mem") or 8), ostype=OS_TYPES[os_key][0],
                       vga="std" if b.get("gpu") else "virtio", hostpci={0: "0000:01:00,pcie=1"} if b.get("gpu") else {},
                       started=time.time() if b.get("running") else None, demo_what=OS_TYPES[os_key][1])
    STATE["added"].append(vmid)
    await _refresh()
    return web.json_response({"id": vmid})


@A.routes.post("/api/demo/service")
async def demo_add_service(req):
    b = await _json(req)
    icon = _slug(b.get("icon") or b.get("name"))
    name = (b.get("name") or icon.replace("-", " ").title()).strip()
    via = b.get("via") if b.get("via") in ("caddy", "port", "notes") else "caddy"
    vmid = _free_id(207, 300)
    port = APP_PORTS.get(icon, 8080)
    WORLD[vmid] = dict(type="lxc", name=_slug(name), status="running", cores=2, mem=2, ip=f"10.0.1.{vmid - 200}",
                       hostpci={}, started=time.time(), demo_what=f"{name} · {via}")
    if via == "caddy":
        key = _slug(name)
        ROUTES.append((key, vmid, port))
        A_app["cfg"]["services"][key] = {"name": name, "icon": icon}
    else:
        DISCOVERED.append((vmid, port, name, icon, via))
    STATE["added"].append(vmid)
    await _refresh()
    return web.json_response({"id": vmid})


@A.routes.post("/api/demo/remove")
async def demo_remove(req):
    vmid = int((await _json(req)).get("id", 0))
    if vmid in STATE["added"]:
        STATE["added"].remove(vmid)
        WORLD.pop(vmid, None)
        ROUTES[:] = [r for r in ROUTES if r[1] != vmid]
        DISCOVERED[:] = [d for d in DISCOVERED if d[0] != vmid]
        await _refresh()
    return web.json_response({"ok": True})


@A.routes.post("/api/demo/world")
async def demo_world(req):
    b = await _json(req)
    if "weather" in b:
        STATE["weather"] = b["weather"] if b["weather"] in ("clear", "partly", "overcast", "rain", "thunder", "snow", "fog") else ""
    if "update" in b:
        STATE["update"] = bool(b["update"])
        if "update" in A_app:
            A_app["update"].value = None   # the next check asks afresh, as after a real release
    await _refresh()
    return web.json_response({"ok": True})


@A.routes.post("/api/demo/reset")
async def demo_reset(req):
    world, routes, found = _initial
    import copy
    WORLD.clear(); WORLD.update(copy.deepcopy(world))
    ROUTES[:] = copy.deepcopy(routes)
    DISCOVERED[:] = copy.deepcopy(found)
    STATE.update(weather="", update=True, added=[], fail=None, apt_checked=APT_CHECKED)
    QEMU_LOG.clear()
    GRABBED.clear()
    for vmid in list(A_app["app"]["input"].given) if "app" in A_app else []:
        A_app["app"]["input"].forget(vmid)
    if "app" in A_app:
        for sid in A_app["app"]["seats"].kiosk_seats():
            A_app["app"]["seats"].set(sid, shows="menu")
    await _refresh()
    return web.json_response({"ok": True})


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
    caddy.static_ips = demo_static_ips
    discover.discover = demo_discover
    L.run = demo_run
    from . import inputs
    inputs.host_units = demo_units
    inputs.monitor = demo_monitor
    inputs.Passer.grabbed = staticmethod(lambda path: path in GRABBED)
    G.pci_mappings = lambda: MAPPINGS
    G.local_node = lambda: NODE
    DDC.switch_to_gpu = switch_input
    DDC.power = demo_power
    weather.get = demo_weather
    wol.send = demo_wake
    update.status = demo_update_status
    app = A.make_app()
    app["demo"] = True

    async def remember(app):
        for k in ("resources", "services", "discovered", "update", "cfg"):
            A_app[k] = app[k]
        A_app["app"] = app
    app.on_startup.append(remember)
    global _initial
    _initial = _snapshot()
    return app


def run(host="127.0.0.1", port=8900):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = make_app()
    if host not in ("127.0.0.1", "localhost", "::1"):
        # Opened from other devices on purpose: answer to any host name, from any address
        # (each of them is the "web" seat, as a browser behind the reverse proxy would be).
        app["cfg"]["allowed_hosts"] = ["*"]
        app["cfg"]["web"] = {"enabled": True, "allow_from": ["0.0.0.0/0", "::/0"]}
    web.run_app(app, host=host, port=port, print=None, access_log=None)
