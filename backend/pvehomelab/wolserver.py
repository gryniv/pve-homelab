"""Wake-on-LAN for VMs: a magic packet for a VM's network card starts that VM.

Moonlight ("Wake PC"), a phone app or a router sends the packet to the broadcast address; the host
hears it, finds the VM whose netN has that MAC address and starts it, as root. Off by default, and
only for the VMs listed (wol_listen.vms), from the networks listed (wol_listen.from, empty: any).
A magic packet carries no password worth the name, so the list is the owner's consent.
It never switches a monitor or hands over input: whoever sent it is somewhere else.
"""

import asyncio
import glob
import ipaddress
import os
import re
import time

from . import gpus as G
from .util import log, pvesh_create

MAC = re.compile(r"(?:^|,)\w+=([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
EVERY = 60     # s between two starts of one VM


def parse_magic(data):
    """The MAC address a Wake-on-LAN packet wakes ("aa:bb:cc:dd:ee:ff"), or None."""
    i = data.find(b"\xff" * 6)
    while i >= 0:
        body = data[i + 6:i + 6 + 96]
        if len(body) == 96:
            mac = body[:6]
            if mac != b"\xff" * 6 and body == mac * 16:
                return ":".join(f"{b:02x}" for b in mac)
        i = data.find(b"\xff" * 6, i + 1)
    return None


def vm_macs(read=None):
    """{mac: vmid} from the netN lines of every VM on this node."""
    def _read(p):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    read = read or _read
    out = {}
    for p in glob.glob("/etc/pve/qemu-server/*.conf"):
        name = os.path.basename(p)[:-5]
        if not name.isdigit():
            continue
        for line in read(p).split("\n[", 1)[0].splitlines():
            key, _, val = line.partition(":")
            if re.fullmatch(r"net\d+", key.strip()):
                for mac in MAC.findall(val.strip()):
                    out[mac.lower()] = int(name)
    return out


class Listener(asyncio.DatagramProtocol):
    def __init__(self, server):
        self.server = server

    def datagram_received(self, data, addr):
        asyncio.get_running_loop().create_task(self.server.packet(data, addr[0]))


class WolServer:
    def __init__(self, app):
        self.app = app
        self.transports = []
        self.last = {}         # vmid -> time it was last started this way
        self.macs = vm_macs

    def cfg(self):
        return self.app["cfg"].get("wol_listen") or {}

    async def start(self):
        c = self.cfg()
        if not c.get("enabled"):
            return
        loop = asyncio.get_running_loop()
        for port in c.get("ports") or [9]:
            try:
                tr, _ = await loop.create_datagram_endpoint(lambda: Listener(self), local_addr=("0.0.0.0", int(port)), allow_broadcast=True)
                self.transports.append(tr)
                log.info("Wake-on-LAN for VMs %s: listening on UDP %s", c.get("vms"), port)
            except OSError as e:
                log.warning("Wake-on-LAN: UDP %s: %s", port, e)

    def stop(self):
        for tr in self.transports:
            tr.close()
        self.transports = []

    def _allowed_from(self, ip):
        nets = self.cfg().get("from") or []
        if not nets:
            return True
        try:
            a = ipaddress.ip_address(ip)
            return any(a in ipaddress.ip_network(str(n), strict=False) for n in nets)
        except ValueError:
            return False

    async def packet(self, data, ip):
        """A packet came in: start the VM it is for, if that is allowed. Returns the vmid started."""
        mac = parse_magic(data)
        if not mac:
            return None
        vmid = self.macs().get(mac)
        c = self.cfg()
        if vmid is None or vmid not in (c.get("vms") or []) or not self._allowed_from(ip):
            log.info("Wake-on-LAN from %s for %s: not for a listed VM, or not from a listed network", ip, mac)
            return None
        now = time.time()
        if now - self.last.get(vmid, 0) < EVERY:
            return None
        running = await self.app["running"](fresh=True)
        if vmid in running:
            return None
        # its GPU may be busy with another system
        for g in await G.list_gpus(running):
            if vmid in g["assigned_vms"] and g["running_vm"] not in (None, vmid):
                log.warning("Wake-on-LAN for VM %s: its GPU %s is busy with VM %s", vmid, g["pci"], g["running_vm"])
                return None
        limits = self.app.get("limits")
        if limits and not limits.may_start(vmid):
            log.info("Wake-on-LAN for VM %s: outside its allowed time", vmid)
            return None
        self.last[vmid] = now
        log.info("Wake-on-LAN from %s: starting VM %s", ip, vmid)
        await pvesh_create(f"/nodes/{self.app['cfg']['node']}/qemu/{vmid}/status/start")
        self.app["resources"].invalidate()
        return vmid
