"""Display GPUs from sysfs: driver, connected monitors (EDID) and which VM holds them."""

import glob
import os
import re
import socket

from .util import run

PCI = "/sys/bus/pci/devices"
_names = {}


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def parse_edid(raw):
    if len(raw) < 128 or raw[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    m = (raw[8] << 8) | raw[9]
    vendor = "".join(chr(((m >> s) & 31) + 64) for s in (10, 5, 0))
    name = serial = ""
    for i in range(54, 126, 18):
        blk = raw[i:i + 18]
        if blk[:3] == b"\0\0\0" and blk[3] in (0xFC, 0xFF):
            txt = blk[5:].split(b"\n")[0].decode(errors="ignore").strip()
            if blk[3] == 0xFC:
                name = txt
            else:
                serial = txt
    if not serial:
        serial = str(int.from_bytes(raw[12:16], "little"))
    return {"vendor": vendor, "name": name or vendor, "serial": serial}


def connectors(pci):
    out = []
    for card in glob.glob(f"{PCI}/{pci}/drm/card*"):
        cname = os.path.basename(card)
        for c in sorted(glob.glob(f"/sys/class/drm/{cname}-*")):
            conn = os.path.basename(c)[len(cname) + 1:]
            if conn.startswith("Writeback"):
                continue
            status = _read(f"{c}/status")
            mon = None
            if status == "connected":
                try:
                    with open(f"{c}/edid", "rb") as f:
                        mon = parse_edid(f.read())
                except OSError:
                    pass
            out.append({"name": conn, "connected": status == "connected", "monitor": mon})
    return out


async def pretty_name(pci):
    if pci not in _names:
        try:
            line = await run("lspci", "-mm", "-s", pci)
            parts = re.findall(r'"([^"]*)"', line)
            dev = parts[2] if len(parts) > 2 else pci
            m = re.search(r"\[([^\]]+)\]", dev)
            _names[pci] = (m.group(1) if m else dev).replace("GeForce ", "")
        except Exception:
            _names[pci] = pci
    return _names[pci]


MAPPING_FILE = "/etc/pve/mapping/pci.cfg"
_mappings = {"mtime": None, "data": {}}


def parse_pci_mappings(text):
    """PVE 8+ resource mappings (/etc/pve/mapping/pci.cfg) -> {name: [{node, path}, ...]}.
    A mapping is a name line followed by indented `map key=value,...` lines, one per node."""
    out, name = {}, None
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            name = line.strip()
            out.setdefault(name, [])
            continue
        body = line.strip()
        if name is None or not body.startswith("map "):
            continue
        kv = dict(p.split("=", 1) for p in body[4:].split(",") if "=" in p)
        if kv.get("path"):
            out[name].append({"node": kv.get("node", ""), "path": kv["path"]})
    return out


def pci_mappings():
    """The mappings of this cluster, re-read when the file changes."""
    try:
        mtime = os.stat(MAPPING_FILE).st_mtime
    except OSError:
        return {}
    if mtime != _mappings["mtime"]:
        _mappings.update(mtime=mtime, data=parse_pci_mappings(_read(MAPPING_FILE)))
    return _mappings["data"]


def local_node():
    return socket.gethostname().split(".")[0]


def hostpci_devices(value, node=None, mappings=None):
    """PCI addresses (domain included, function optional) behind one hostpciN value:
    "0000:01:00", "01:00.0;01:00.1,x-vga=1", "host=…" or "mapping=<name>,…" (resolved for `node`)."""
    first = (value or "").split(",")[0].strip()
    if first.startswith("mapping="):
        maps = (pci_mappings() if mappings is None else mappings).get(first[8:], [])
        node = node or local_node()
        hit = next((m for m in maps if m["node"] == node), None) or (maps[0] if len(maps) == 1 else None)
        devs = hit["path"].split(";") if hit else []
    else:
        devs = first.replace("host=", "").split(";")
    return [(d if d.count(":") == 2 else "0000:" + d).lower() for d in devs if d]


def vm_gpus():
    """{pci_prefix: [vmid, ...]} from VM configs (hostpci lines, resource mappings resolved)."""
    used = {}
    for conf in glob.glob("/etc/pve/qemu-server/*.conf"):
        vmid = int(os.path.basename(conf).split(".")[0])
        for line in _read(conf).split("\n[")[0].splitlines():
            m = re.match(r"hostpci\d+:\s*(.+)$", line)
            if m:
                for dev in hostpci_devices(m.group(1)):
                    used.setdefault(dev, []).append(vmid)
    return used


def gpu_of(addr):
    """Map a hostpci address (maybe without function) to its GPU function 0."""
    return (addr if "." in addr else addr + ".0").lower()


async def list_gpus(running_vmids):
    used = vm_gpus()
    gpus = []
    for dev in sorted(glob.glob(f"{PCI}/*")):
        cls = _read(f"{dev}/class")
        if not cls.startswith("0x03"):
            continue
        pci = os.path.basename(dev)
        driver = os.path.basename(os.path.realpath(f"{dev}/driver")) if os.path.exists(f"{dev}/driver") else None
        vms = [v for a, vs in used.items() if gpu_of(a) == pci for v in vs]
        gpus.append({
            "pci": pci,
            "name": await pretty_name(pci),
            "vendor": {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}.get(_read(f"{dev}/vendor"), "other"),
            "driver": driver,
            "integrated": pci.startswith("0000:00:") or (driver == "amdgpu" and _is_apu(dev)),
            "boot_vga": _read(f"{dev}/boot_vga") == "1",
            "connectors": connectors(pci),
            "assigned_vms": vms,
            "running_vm": next((v for v in vms if v in running_vmids), None),
        })
    return gpus


def _is_apu(dev):
    # AMD APUs expose no dedicated VRAM beyond a small carve-out.
    vram = _read(f"{dev}/mem_info_vram_total", "0")
    return vram.isdigit() and int(vram) <= 2 * 1024 ** 3
