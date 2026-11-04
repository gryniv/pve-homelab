"""The keyboard, mouse and gamepad of a screen on the host go into a system with its monitor.

Keyboards and mice go through evdev (QEMU's input-linux objects): QEMU takes the device for itself
(an exclusive grab) and gives it back when both Ctrl keys are pressed (`grab-toggle`). A watcher
notices the device is free again; then the menu takes the objects out of QEMU and switches the
monitor back. Gamepads go as USB devices plugged into the VM for the session (device_add, not the
VM's config). Nothing here writes a VM's config: when the VM stops, all of it is gone with QEMU.

What the VM already has (its own usbN: a keyboard by id, a port, or a mapping) is left alone.
"""

import asyncio
import fcntl
import glob
import os
import re

from .util import log, pvesh_create

PROC = "/proc/bus/input/devices"
BY_ID = "/dev/input/by-id"
USB_CFG = "/etc/pve/mapping/usb.cfg"
EVIOCGRAB = 0x40044590
HOTKEYS = ("ctrl-ctrl", "alt-alt", "shift-shift", "meta-meta", "scrolllock", "ctrl-scrolllock")
SKIP = re.compile(r"power button|sleep button|video bus|pc speaker|hda |hdmi|jack|ir receiver|lid switch|"
                  r"consumer control|system control|wmi|acpi|webcam|camera", re.I)


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def parse_devices(text):
    """/proc/bus/input/devices -> [{name, phys, sysfs, event, kind, vendor, product, bus}]."""
    out = []
    for block in (text or "").strip().split("\n\n"):
        d = {}
        for line in block.splitlines():
            tag, _, rest = line.partition(": ")
            if tag == "I":
                d.update({k.lower(): v for k, v in re.findall(r"(\w+)=(\w+)", rest)})
            elif tag == "N":
                d["name"] = rest.partition("=")[2].strip('"')
            elif tag == "P":
                d["phys"] = rest.partition("=")[2]
            elif tag == "S":
                d["sysfs"] = rest.partition("=")[2]
            elif tag == "U":
                d["uniq"] = rest.partition("=")[2]
            elif tag == "H":
                d["handlers"] = rest.partition("=")[2].split()
            elif tag == "B" and rest.startswith("EV="):
                d["ev"] = int(rest[3:], 16)
        ev = next((h for h in d.get("handlers", []) if h.startswith("event")), None)
        if not ev or not d.get("name") or SKIP.search(d["name"]):
            continue
        hs = d.get("handlers", [])
        kind = ("pad" if any(h.startswith("js") for h in hs) else "keyboard" if "kbd" in hs and d.get("ev", 0) & 0x100002 == 0x100002
                else "mouse" if any(h.startswith("mouse") for h in hs) else None)
        if not kind:
            continue
        out.append({"name": d["name"], "phys": d.get("phys", ""), "sysfs": d.get("sysfs", ""), "event": ev, "kind": kind,
                    "vendor": d.get("vendor", "").lower(), "product": d.get("product", "").lower(), "bus": d.get("bus", "")})
    return out


def usb_parent(sysfs):
    """The USB device a node hangs off: "1-3" or "1-3.2" (a port behind a hub); None for Bluetooth."""
    m = re.search(r"/usb\d+/(\d+-[\d.]+)(?:/|$)", sysfs or "")
    return m.group(1) if m else None


def by_id(root=BY_ID):
    """{eventN: /dev/input/by-id/<stable name>} (names survive replugging, eventN may not)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "*"))):
        target = os.path.basename(os.path.realpath(p))
        if target.startswith("event"):
            out.setdefault(target, p)
    return out


def parse_usb_mappings(text):
    """/etc/pve/mapping/usb.cfg -> {name: [{node, id, path}]}."""
    out, name = {}, None
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            name = line.strip()
            out.setdefault(name, [])
        elif name and line.strip().startswith("map "):
            kv = dict(p.split("=", 1) for p in line.strip()[4:].split(",") if "=" in p)
            out[name].append(kv)
    return out


def vm_usb(conf_text, node, mappings):
    """What a VM config passes through as USB: ({"vvvv:pppp", ...}, {"1-3", ...})."""
    ids, ports = set(), set()
    for m in re.finditer(r"^usb\d+:\s*(\S+)", conf_text or "", re.M):
        first = m.group(1).split(",")[0]
        if first.startswith("host="):
            v = first[5:]
            (ids if ":" in v else ports).add(v.lower())
        elif first.startswith("mapping="):
            for e in mappings.get(first[8:], []):
                if e.get("node") in (None, "", node):
                    if e.get("id"):
                        ids.add(e["id"].lower())
                    if e.get("path"):
                        ports.add(e["path"])
    return ids, ports


def units(devices, links, vm_confs, node, mappings):
    """Devices grouped by the USB device they hang off (a wireless receiver: one row for its keyboard
    and mouse), each with what it is, its evdev nodes and which VM already has it.
    vm_confs: {vmid: config text}."""
    taken = {vmid: vm_usb(text, node, mappings) for vmid, text in vm_confs.items()}
    groups = {}
    for d in devices:
        parent = usb_parent(d["sysfs"])
        key = parent or f"{d['bus']}:{d['vendor']}:{d['product']}"
        u = groups.setdefault(key, {"id": key, "name": d["name"], "kinds": [], "evdev": [], "usb": None, "in_vm": None})
        if d["kind"] not in u["kinds"]:
            u["kinds"].append(d["kind"])
        u["evdev"].append({"kind": d["kind"], "path": links.get(d["event"], f"/dev/input/{d['event']}")})
        if parent:
            bus, _, port = parent.partition("-")
            u["usb"] = {"bus": int(bus), "port": port, "id": f"{d['vendor']}:{d['product']}"}
            for vmid, (ids, ports) in taken.items():
                if u["usb"]["id"] in ids or parent in ports:
                    u["in_vm"] = vmid
    return list(groups.values())


def vm_configs():
    """{vmid: config text} of every VM on this node."""
    out = {}
    for p in glob.glob("/etc/pve/qemu-server/*.conf"):
        name = os.path.basename(p)[:-5]
        if name.isdigit():
            out[int(name)] = _read(p).split("\n[", 1)[0]
    return out


def host_units(node):
    """This host's input devices, now, and which VM already has each."""
    return units(parse_devices(_read(PROC)), by_id(), vm_configs(), node, parse_usb_mappings(_read(USB_CFG)))


# ---------------------------------------------------------------- QEMU's monitor

def hmp(value):
    """A value inside an HMP option list: commas doubled."""
    return str(value).replace(",", ",,")


async def monitor(node, vmid, command):
    out = await pvesh_create(f"/nodes/{node}/qemu/{vmid}/monitor", command=command)
    return out if isinstance(out, str) else ""


def grabbed(path):
    """Does someone (QEMU) hold this evdev node exclusively? Grab and let go at once to find out."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 1)
    except OSError:
        return True          # EBUSY: it is QEMU's
    else:
        fcntl.ioctl(fd, EVIOCGRAB, 0)
        return False
    finally:
        os.close(fd)


class Passer:
    """Input handed to VMs: what was put where, and the watcher that brings it back."""

    def __init__(self, app):
        self.app = app
        self.given = {}       # vmid -> {"seat", "objects": [ids], "devices": [ids], "keyboards": [paths]}
        self.watchers = {}

    def settings(self):
        return self.app["cfg"].get("input") or {}

    async def give(self, sid, vmid, units_now):
        """Put the chosen devices of this host into VM `vmid`. Returns the names of what went in."""
        cfg, node = self.settings(), self.app["cfg"]["node"]
        if cfg.get("mode", "evdev") == "off":
            return []
        chosen = cfg.get("devices") or "auto"
        picked = [u for u in units_now if not u["in_vm"] and (chosen == "auto" or u["id"] in chosen)]
        objects, devices, keyboards, names = [], [], [], []
        hotkey = cfg.get("hotkey", "ctrl-ctrl")
        n = 0
        for u in picked:
            for ev in u["evdev"]:
                if ev["kind"] == "pad":
                    continue
                oid = f"phl{n}"
                n += 1
                opts = f"input-linux,id={oid},evdev={hmp(ev['path'])}"
                if ev["kind"] == "keyboard":
                    opts += f",grab_all=on,repeat=on,grab-toggle={hotkey}"
                    keyboards.append(ev["path"])
                await monitor(node, vmid, f"object_add {opts}")
                objects.append(oid)
            if "pad" in u["kinds"] and u["usb"] and cfg.get("gamepads", "usb") == "usb":
                did = f"phlpad{len(devices)}"
                await monitor(node, vmid, f"device_add usb-host,hostbus={u['usb']['bus']},hostport={hmp(u['usb']['port'])},id={did}")
                devices.append(did)
            names.append(u["name"])
        if not objects and not devices:
            return []
        self.given[vmid] = {"seat": sid, "objects": objects, "devices": devices, "keyboards": keyboards}
        self.app["seats"].set(sid, input=vmid)
        log.info("input of seat %s to VM %s: %s", sid, vmid, ", ".join(names))
        if keyboards:
            self.watchers[vmid] = asyncio.create_task(self._watch(vmid))
        return names

    async def take_back(self, vmid, monitor_too=True):
        """Out of QEMU (if it still runs), and the monitor back to the menu."""
        g = self.given.pop(vmid, None)
        w = self.watchers.pop(vmid, None)
        if w and w is not asyncio.current_task():
            w.cancel()
        if not g:
            return
        node = self.app["cfg"]["node"]
        for oid in g["objects"]:
            try:
                await monitor(node, vmid, f"object_del {oid}")
            except Exception as e:
                log.debug("object_del %s: %s", oid, e)
        for did in g["devices"]:
            try:
                await monitor(node, vmid, f"device_del {did}")
            except Exception as e:
                log.debug("device_del %s: %s", did, e)
        self.app["seats"].set(g["seat"], input="menu")
        if monitor_too:
            try:
                await self.app["launcher"].focus(g["seat"], "menu")
            except Exception as e:
                log.warning("monitor back to the menu: %s", e)
        log.info("input of seat %s back from VM %s", g["seat"], vmid)

    async def _watch(self, vmid, every=0.25):
        """Both Ctrl in the VM: QEMU lets the keyboard go. Then the menu takes everything back."""
        await asyncio.sleep(1.0)   # QEMU takes the grab right after object_add
        loop = asyncio.get_running_loop()
        while vmid in self.given:
            kbs = self.given[vmid]["keyboards"]
            held = await loop.run_in_executor(None, lambda: any(self.grabbed(p) for p in kbs))
            if not held:
                await self.take_back(vmid)
                return
            await asyncio.sleep(every)

    grabbed = staticmethod(grabbed)

    def forget(self, vmid):
        """The VM stopped: what was in it went with QEMU."""
        g = self.given.pop(vmid, None)
        w = self.watchers.pop(vmid, None)
        if w:
            w.cancel()
        if g:
            self.app["seats"].set(g["seat"], input="menu")
