"""Starting a system on a GPU wired to the monitor the user is looking at."""

import asyncio
import itertools
import json
import os
import re
import time

from . import config
from . import gpus as G
from .i18n import _
from .pve import PVEError
from .util import log, run

_job_ids = itertools.count(1)

HOSTPCI = re.compile(r"^hostpci(\d+):\s*(.*)$", re.M)
VGA = re.compile(r"^vga:\s*(.*)$", re.M)
FOLLOW_WINDOW = 180      # s: a VM up for less than this was just started
BOOT_WINDOW = 600        # s: the host is still booting (its onboot VMs come up now)


def pci_addr(val, node=None, mappings=None):
    """The (first) PCI address in a hostpciN value ("0000:01:00.0", "01:00", "host=01:00.0;01:00.1,x-vga=1",
    or a PVE resource mapping "mapping=rtx,pcie=1"); "" when a mapping can't be resolved."""
    devs = G.hostpci_devices(val, node, mappings)
    return devs[0] if devs else ""


def plan_hostpci(conf, display, gpu, node=None, mappings=None, remembered=None):
    """Where `gpu` goes in a VM config (text of `qm config`): the hostpci slot that already holds a
    display GPU, else the slot VirGL emptied (`remembered`: {slot: value} it took out), else the
    first free one. Returns (slot, new value, old value or None). The new value keeps that entry's
    options (x-vga, romfile, rombar, ...) and its form: an entry that names a resource mapping
    names the mapping of the new GPU (raw address if it has none), a raw address stays raw, and a
    new entry uses the GPU's mapping when there is one."""
    target = gpu.rsplit(".", 1)[0]  # whole device: VGA + its audio function
    mapping = G.mapping_for(target, node, mappings)
    used, slot, old = set(), None, None
    for m in HOSTPCI.finditer(conf):
        n, val = int(m.group(1)), m.group(2).strip()
        used.add(n)
        if slot is None and G.gpu_of(pci_addr(val, node, mappings) or "-") in display:
            slot, old = n, val
    base = old
    if slot is None:
        slot, base = next(((n, v) for n, v in sorted((remembered or {}).items()) if n not in used), (None, None))
    if slot is None:
        slot = next(i for i in range(16) if i not in used)
    if base is None:
        return slot, f"{f'mapping={mapping}' if mapping else target},pcie=1", None
    dev = f"mapping={mapping}" if mapping and base.startswith("mapping=") else target
    opts = [o for o in base.split(",")[1:] if o]
    if not any(o.split("=")[0] == "pcie" for o in opts):
        opts.append("pcie=1")
    return slot, ",".join([dev] + opts), old


def _remembered_path(vmid):
    return os.path.join(config.STATE_DIR, "launch", f"{int(vmid)}.json")


def remembered(vmid):
    """What the last switch to VirGL took out of the VM: {"hostpci": {slot: value}, "vga": old}."""
    try:
        with open(_remembered_path(vmid), encoding="utf-8") as f:
            d = json.load(f)
        return {"hostpci": {int(k): str(v) for k, v in (d.get("hostpci") or {}).items()}, "vga": d.get("vga")}
    except (OSError, ValueError, AttributeError, TypeError):
        return {"hostpci": {}, "vga": None}


def remember(vmid, data):
    path = _remembered_path(vmid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**data, "hostpci": {str(k): v for k, v in data["hostpci"].items()}, "at": int(time.time())}, f)
    os.replace(tmp, path)


def forget(vmid):
    try:
        os.remove(_remembered_path(vmid))
    except OSError:
        pass


def host_uptime():
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return float("inf")


class Job:
    def __init__(self, steps, owner=None):
        self.id = next(_job_ids)
        self.owner = owner
        self.created = time.time()
        self.steps = [{"text": s, "state": "todo"} for s in steps]
        self.error = None
        self.done = False
        self.result = {}

    def step(self, i, state="now"):
        for j, s in enumerate(self.steps):
            if j < i:
                s["state"] = "done"
        self.steps[i]["state"] = state

    def finish(self):
        for s in self.steps:
            s["state"] = "done"
        self.done = True

    def as_dict(self):
        return {"id": self.id, "steps": self.steps, "error": self.error, "done": self.done, "result": self.result}


class Launcher:
    def __init__(self, app):
        self.app = app
        self.cfg = app["cfg"]
        self.jobs = {}
        self.watch = {}  # vmid -> (monitor, seat gpu)
        self._locks = {}  # "gpu:<pci>" / "vm:<id>" -> asyncio.Lock: one launch per GPU and per VM at a time

    def _lock(self, key):
        return self._locks.setdefault(key, asyncio.Lock())

    # ---------- discovery ----------
    async def systems(self, t):
        node, tag = self.cfg["node"], self.cfg["systems_tag"]
        extra = set(self.cfg.get("systems_extra") or [])
        res = await self.app["pve"].get(t, "/cluster/resources", type="vm")
        out = []
        for g in res or []:
            tagged = tag in (g.get("tags") or "").split(";") or g["vmid"] in extra
            if g.get("type") != "qemu" or not tagged:
                continue
            conf = await self.app["pve"].get(t, f"/nodes/{node}/qemu/{g['vmid']}/config")
            gpu_list = [G.gpu_of(a) for k, v in conf.items() if k.startswith("hostpci")
                        for a in [pci_addr(str(v), node)] if a]
            out.append({
                "vmid": g["vmid"], "name": conf.get("name") or g.get("name"),
                "status": g.get("status"), "ostype": conf.get("ostype", ""),
                "suspended": conf.get("lock") == "suspended",
                "vga": (conf.get("vga") or "").split(",")[0],
                "cores": conf.get("cores", 1) * conf.get("sockets", 1),
                "memory": int(conf.get("memory", 0)), "gpus": gpu_list,
                "uptime": g.get("uptime", 0),
            })
        return sorted(out, key=lambda s: s["vmid"])

    _addr = staticmethod(pci_addr)

    async def options(self, seat_id, vm, seen=None):
        """GPUs the user could start `vm` on from this seat. `seen`: the VMs this user may see;
        a GPU busy with any other VM says so without naming it."""
        opts = await self._options(seat_id, vm)
        if seen is not None:
            for o in opts:
                if o["busy_vm"] and o["busy_vm"] not in seen:
                    o["busy_vm"] = 0
                    if o["disabled"]:
                        o["disabled"] = _("busy_other")
        return opts

    async def _options(self, seat_id, vm):
        seat = self.cfg["seats"][seat_id]
        if not seat.get("gpu"):
            return await self._remote_options(vm)
        ddc = self.app["ddc"]
        mon = ddc.monitor_for_gpu(seat["gpu"])
        wired = list(self.cfg["monitors"][mon]["inputs"]) if mon else []
        running = await self.app["running"]()
        all_gpus = {g["pci"]: g for g in await G.list_gpus(running)}
        opts = []
        for pci in dict.fromkeys(wired + [seat["gpu"]]):
            g = all_gpus.get(pci)
            if not g:
                continue
            is_seat = pci == seat["gpu"]
            busy_vm = g["running_vm"] if g["running_vm"] not in (None, vm["vmid"]) else None
            # The seat's own GPU draws this menu. Unless full passthrough is allowed, a system
            # "on the iGPU" shares it through VirGL and is shown inside the menu.
            virgl = is_seat and not self.cfg["launch"]["allow_igpu"]
            opt = {
                "pci": pci, "name": g["name"], "vendor": g["vendor"], "integrated": g["integrated"],
                "this_monitor": pci in wired, "busy_vm": busy_vm, "is_seat_gpu": is_seat,
                "mode": "virgl" if virgl else "passthrough", "disabled": None,
            }
            if virgl:
                if vm["status"] == "running" and vm["gpus"]:
                    opt["disabled"] = _("running_elsewhere")
            elif busy_vm:
                opt["disabled"] = _("busy", vm=busy_vm)
            elif vm.get("suspended") and pci not in vm["gpus"]:
                opt["disabled"] = _("suspended")
            elif not self.cfg["launch"]["assign_gpu"] and pci not in vm["gpus"]:
                opt["disabled"] = _("other_gpu")
            opts.append(opt)
        return opts

    async def _remote_options(self, vm):
        """From a browser elsewhere (the "web" seat): its screen right here (noVNC), or a start on
        the GPU it already has, with its own monitor. Nothing is reassigned, no input switched."""
        running = await self.app["running"]()
        all_gpus = {g["pci"]: g for g in await G.list_gpus(running)}
        opts = [{"pci": "console", "name": _("browser_console"), "vendor": "", "integrated": True,
                 "this_monitor": False, "busy_vm": None, "is_seat_gpu": True, "mode": "console",
                 "disabled": _("no_display") if vm["vga"] == "none" else None}]
        for pci in vm["gpus"]:
            g = all_gpus.get(pci)
            if not g:   # passed through, but not a GPU (its audio or USB function, say)
                continue
            busy = g.get("running_vm") if g.get("running_vm") not in (None, vm["vmid"]) else None
            opts.append({"pci": pci, "name": g["name"], "vendor": g["vendor"], "integrated": g["integrated"],
                         "this_monitor": False, "busy_vm": busy, "is_seat_gpu": False, "mode": "remote",
                         "disabled": _("busy", vm=busy) if busy else None})
        return opts

    async def _launch_remote(self, t, vm, opt):
        pve, node, vmid = self.app["pve"], self.cfg["node"], vm["vmid"]
        console = opt["mode"] == "console"
        if opt["disabled"]:
            raise PVEError(409, _("gpu_disabled", name=opt["name"], why=opt["disabled"]))
        if vm["status"] == "running":
            async def show(job):
                job.step(0)
                if console:
                    job.result = {"console": vmid}
            return self.start_job(show, [_("step_show", vm=vm["name"]) if console
                                         else _("step_running", vm=vm["name"], gpu=opt["name"])])
        if not await pve.can(t, f"/vms/{vmid}", "VM.PowerMgmt"):
            raise PVEError(403, _("no_power"))
        steps = [_("step_wake" if vm["suspended"] else "step_start", vm=vm["name"], id=vmid)]
        if console:
            steps.append(_("step_show_short"))

        async def go(job):
            async with self._lock(f"vm:{vmid}"):
                if vmid in await self.app["running"](fresh=True):
                    raise PVEError(409, _("already_running", vm=vm["name"]))
                job.step(0)
                upid = await pve.post(t, f"/nodes/{node}/qemu/{vmid}/status/start")
                await pve.wait_task(t, node, upid, timeout=180)
            if console:
                job.step(1)
                await asyncio.sleep(1.5)
                job.result = {"console": vmid}
        return self.start_job(go, steps)

    # ---------- actions ----------
    def start_job(self, coro_fn, steps, owner=None):
        job = Job(steps, owner)
        self.jobs[job.id] = job

        async def runner():
            try:
                await coro_fn(job)
                job.finish()
            except Exception as e:
                log.exception("launch job failed")
                job.error = str(e)
                job.done = True
        asyncio.create_task(runner())
        return job

    async def launch(self, t, seat_id, vmid, gpu, resources=None):
        """Start (or show, or switch to) `vmid` on `gpu`; the job is its starter's alone to follow.
        `resources` ({memory: MB, cores}) are written into a stopped VM's config first, with the
        user's own ticket (Proxmox checks VM.Config.Memory / VM.Config.CPU); they stay there."""
        if resources:
            await self._set_resources(t, vmid, resources)
        job = await self._launch(t, seat_id, vmid, gpu)
        job.owner = t.user
        return job

    async def _set_resources(self, t, vmid, resources):
        if vmid in await self.app["running"](fresh=True):
            raise PVEError(409, _("resources_running"))
        data = {k: int(v) for k, v in resources.items() if k in ("memory", "cores")}
        if data:
            await self.app["pve"].req(t, "PUT", f"/nodes/{self.cfg['node']}/qemu/{vmid}/config", data)
            log.info("VM %s before its start: %s", vmid, ", ".join(f"{k} {v}" for k, v in data.items()))

    async def _launch(self, t, seat_id, vmid, gpu):
        pve, node = self.app["pve"], self.cfg["node"]
        vm = next((s for s in await self.systems(t) if s["vmid"] == vmid), None)
        if not vm:
            raise PVEError(404, _("no_system"))
        opts = {o["pci"]: o for o in await self.options(seat_id, vm)}
        opt = opts.get(gpu)
        if not opt:
            raise PVEError(400, _("not_wired"))
        if opt["mode"] in ("console", "remote"):
            return await self._launch_remote(t, vm, opt)
        seat_gpu = self.cfg["seats"][seat_id]["gpu"]
        mon = self.app["ddc"].monitor_for_gpu(seat_gpu)

        if opt["mode"] == "virgl":
            return await self._launch_virgl(t, vm, opt)

        if vm["status"] == "running":
            if gpu not in vm["gpus"]:
                raise PVEError(409, _("running_elsewhere"))

            async def switch(job):
                job.step(0)
                self.watch[vmid] = (mon, seat_gpu)
                if await self.app["ddc"].switch_to_gpu(mon, gpu):
                    self.app["seats"].set(seat_id, shows=vmid)
            return self.start_job(switch, [_("step_switch", gpu=opt["name"])])

        if opt["disabled"]:
            raise PVEError(409, _("gpu_disabled", name=opt["name"], why=opt["disabled"]))
        if not await pve.can(t, f"/vms/{vmid}", "VM.PowerMgmt"):
            raise PVEError(403, _("no_power"))
        need_assign = gpu not in vm["gpus"]
        if need_assign and not await pve.can(t, f"/vms/{vmid}", "VM.Config.HWType"):
            raise PVEError(403, _("no_hw_gpu"))

        steps = []
        if need_assign:
            steps.append(_("step_assign", gpu=opt["name"], vm=vm["name"]))
        steps += [_("step_start", vm=vm["name"], id=vmid), _("step_switch", gpu=opt["name"])]

        async def go(job):
            async with self._lock(f"gpu:{gpu}"), self._lock(f"vm:{vmid}"):
                # Someone may have started another system on this GPU since the dialog opened.
                running = await self.app["running"](fresh=True)
                if vmid in running:
                    raise PVEError(409, _("already_running", vm=vm["name"]))
                holder = next((g["running_vm"] for g in await G.list_gpus(running) if g["pci"] == gpu), None)
                if holder not in (None, vmid):
                    raise PVEError(409, _("gpu_disabled", name=opt["name"], why=_("busy", vm=holder)))
                i, undo = 0, None
                if need_assign:
                    job.step(i)
                    undo = await self._assign_gpu(vmid, gpu, t)
                    i += 1
                job.step(i)
                try:
                    upid = await pve.post(t, f"/nodes/{node}/qemu/{vmid}/status/start")
                except Exception:
                    # Not started: put the VM's GPU back as it was.
                    if undo is not None:
                        await self._undo_assign(vmid, undo)
                    raise
                # From here the VM is (being) started: give the monitor back when it stops,
                # even if the wait or the switch below fails.
                self.watch[vmid] = (mon, seat_gpu)
                await pve.wait_task(t, node, upid, timeout=180)
                if undo is not None:
                    forget(vmid)   # the GPU entry VirGL took out is back for good
                i += 1
                job.step(i)
                await asyncio.sleep(2)
                if mon and await self.app["ddc"].switch_to_gpu(mon, gpu):
                    self.app["seats"].set(seat_id, shows=vmid)
        return self.start_job(go, steps)

    async def _launch_virgl(self, t, vm, opt):
        """Run the VM on the seat's own GPU via VirGL and show it inside the menu (noVNC)."""
        pve, node, vmid = self.app["pve"], self.cfg["node"], vm["vmid"]
        if opt["disabled"]:
            raise PVEError(409, _("gpu_disabled", name=opt["name"], why=opt["disabled"]))
        if vm["status"] == "running":
            async def show(job):
                job.step(0)
                job.result = {"console": vmid}
            return self.start_job(show, [_("step_show", vm=vm["name"])])

        if not await pve.can(t, f"/vms/{vmid}", "VM.PowerMgmt"):
            raise PVEError(403, _("no_power"))
        # A hibernated VM must wake up with the hardware it slept with.
        reconfigure = not vm["suspended"] and (vm["vga"] != "virtio-gl" or vm["gpus"])
        if reconfigure and not await pve.can(t, f"/vms/{vmid}", "VM.Config.HWType"):
            raise PVEError(403, _("no_hw_vga"))

        steps = []
        if reconfigure:
            steps.append(_("step_virgl", gpu=opt["name"]))
        steps += [_("step_wake" if vm["suspended"] else "step_start", vm=vm["name"], id=vmid), _("step_show_short")]

        async def go(job):
            i = 0
            if reconfigure:
                job.step(i)
                await self._to_virgl(vmid)
                i += 1
            job.step(i)
            upid = await pve.post(t, f"/nodes/{node}/qemu/{vmid}/status/start")
            await pve.wait_task(t, node, upid, timeout=180)
            job.step(i + 1)
            await asyncio.sleep(1.5)
            job.result = {"console": vmid}
        return self.start_job(go, steps)

    async def _to_virgl(self, vmid):
        """VirGL on the menu's GPU: the display GPU entries come out of the VM config. What they
        said (x-vga, romfile, a mapping) and the old display are kept beside the config, and the
        next start on a passed-through GPU puts them back."""
        conf = await run("qm", "config", str(vmid))
        display = {g["pci"] for g in await G.list_gpus(set())}
        args = ["qm", "set", str(vmid), "--vga", "virtio-gl,memory=256"]
        drop = {int(m.group(1)): m.group(2).strip() for m in HOSTPCI.finditer(conf)
                if G.gpu_of(pci_addr(m.group(2), self.cfg["node"]) or "-") in display}
        if drop:
            args += ["--delete", ",".join(f"hostpci{n}" for n in sorted(drop))]
        vga = (VGA.search(conf) or [None, None])[1]
        kept = remembered(vmid)
        if drop or not (vga or "").startswith("virtio-gl"):
            remember(vmid, {"hostpci": {**kept["hostpci"], **drop},
                            "vga": kept["vga"] if (vga or "").startswith("virtio-gl") else vga})
        log.info("VM %s -> VirGL %s", vmid, " ".join(args[3:]))
        await run(*args)

    async def _assign_gpu(self, vmid, gpu, t=None):
        """Point the VM's display-GPU hostpci entry at `gpu` (other passthrough stays); after VirGL,
        bring back the entry and the display it had. With the user's ticket `t`, writing a resource
        mapping needs Mapping.Use on it, as in Proxmox itself. Returns what _undo_assign needs."""
        conf = await run("qm", "config", str(vmid))
        display = {g["pci"] for g in await G.list_gpus(set())}
        back = remembered(vmid)
        slot, value, old = plan_hostpci(conf, display, gpu, self.cfg["node"], remembered=back["hostpci"])
        mapping = value.split(",")[0][8:] if value.startswith("mapping=") else None
        if mapping and t is not None and not await self.app["pve"].can(t, f"/mapping/pci/{mapping}", "Mapping.Use"):
            raise PVEError(403, _("no_mapping_use", name=mapping))
        args = ["qm", "set", str(vmid), f"--hostpci{slot}", value]
        vga = (VGA.search(conf) or [None, None])[1]
        if (vga or "").startswith("virtio-gl") and (back["hostpci"] or back["vga"] is not None):
            args += ["--vga", back["vga"]] if back["vga"] else ["--delete", "vga"]
        else:
            vga = None
        log.info("VM %s: hostpci%s %s -> %s%s", vmid, slot, old or "(new)", value, f", vga {vga} -> {back['vga'] or 'default'}" if vga else "")
        await run(*args)
        return (slot, old, vga)

    async def _undo_assign(self, vmid, undo):
        slot, old, vga = (tuple(undo) + (None,))[:3]
        try:
            args = ["qm", "set", str(vmid)]
            args += [f"--hostpci{slot}", old] if old else ["--delete", f"hostpci{slot}"]
            if vga:
                args += ["--vga", vga]
            await run(*args)
            log.info("VM %s: hostpci%s restored", vmid, slot)
        except Exception as e:
            log.warning("VM %s: could not restore hostpci%s (%s): %s", vmid, slot, old, e)

    ADOPT_EVERY = 8   # turns of the watch loop (4 s each): about every half a minute

    def _follows(self, uptime):
        """Does the monitor go to a VM the menu found just started? launch.follow_start:
        "boot" while the host is still coming up (its onboot VMs), "always", or "never"."""
        follow = self.cfg["launch"].get("follow_start", "boot")
        if follow == "never" or uptime is None or uptime >= FOLLOW_WINDOW:
            return False
        return follow == "always" or host_uptime() < BOOT_WINDOW

    async def adopt(self):
        """Watch VMs that hold a GPU wired to a menu monitor though the menu did not start them:
        started before it (an update restarts the menu at night) or from Proxmox itself. Otherwise
        the monitor stays on that GPU's input, with no picture, after the VM stops. One that has
        just started (with the host, or from Proxmox when follow_start is "always") also gets the
        monitor, as if it had been started from the menu."""
        cfg, ddc = self.cfg, self.app["ddc"]
        running = await self.app["running"]()
        uptime = {g["vmid"]: g.get("uptime") for g in await self.app["resources"].get() if g.get("status") == "running"}
        for g in await G.list_gpus(running):
            vm, mon = g["running_vm"], ddc.monitor_for_gpu(g["pci"])
            if not vm or not mon or vm in self.watch:
                continue
            seat_gpu = next((s["gpu"] for s in cfg["seats"].values()
                             if s.get("kiosk") and s.get("gpu") and ddc.monitor_for_gpu(s["gpu"]) == mon), None)
            if seat_gpu:
                self.watch[vm] = (mon, seat_gpu)
                log.info("watching VM %s on monitor %s", vm, mon)
                if self._follows(uptime.get(vm)):
                    log.info("VM %s just started: monitor %s goes to it", vm, mon)
                    try:
                        if await ddc.switch_to_gpu(mon, g["pci"]):
                            self.app["seats"].set(self.app["seats"].seat_of_monitor(ddc, mon), shows=vm)
                    except Exception as e:
                        log.warning("switch to VM %s failed: %s", vm, e)

    async def sync_seats(self):
        """At start: what each menu monitor shows now (the menu may restart while someone is in a VM)."""
        ddc, seats = self.app["ddc"], self.app["seats"]
        running = await self.app["running"]()
        holders = {g["pci"]: g["running_vm"] for g in await G.list_gpus(running) if g["running_vm"]}
        for sid in seats.kiosk_seats():
            mon = ddc.monitor_for_gpu(self.cfg["seats"][sid]["gpu"])
            if not mon:
                continue
            try:
                code = await ddc.current_input(mon)
            except Exception:
                continue
            pci = next((p for p, c in self.cfg["monitors"][mon]["inputs"].items() if c == code), None)
            if pci and holders.get(pci):
                seats.set(sid, shows=holders[pci])

    async def focus(self, sid, to):
        """The monitor of seat `sid` to the menu ("menu") or to VM `to`, already running on a GPU wired
        to it. Returns the VM shown, or None when it is the menu."""
        ddc, seats = self.app["ddc"], self.app["seats"]
        seat_gpu = self.cfg["seats"][sid]["gpu"]
        mon = ddc.monitor_for_gpu(seat_gpu)
        if not mon:
            raise PVEError(409, _("no_monitor"))
        if to == "menu":
            await ddc.switch_to_gpu(mon, seat_gpu)
            seats.set(sid, shows="menu")
            return None
        running = await self.app["running"](fresh=True)
        wired = self.cfg["monitors"][mon]["inputs"]
        gpu = next((g["pci"] for g in await G.list_gpus(running)
                    if g["running_vm"] == to and g["pci"] in wired and g["pci"] != seat_gpu), None)
        if not gpu:
            raise PVEError(409, _("not_on_this_monitor"))
        self.watch.setdefault(to, (mon, seat_gpu))
        if not await ddc.switch_to_gpu(mon, gpu):
            raise PVEError(409, _("not_on_this_monitor"))
        seats.set(sid, shows=to)
        return to

    def on_monitor(self, sid):
        """The VMs running on GPUs wired to seat `sid`'s monitor, the menu knows of (watched)."""
        mon = self.app["ddc"].monitor_for_gpu(self.cfg["seats"][sid]["gpu"])
        return [vm for vm, (m, _g) in self.watch.items() if m == mon]

    async def give_back(self):
        """The watched VMs that stopped: the monitor goes back to the menu."""
        running = await self.app["running"](fresh=True)
        for vmid, (mon, seat_gpu) in list(self.watch.items()):
            if vmid in running:
                continue
            del self.watch[vmid]
            seats = self.app["seats"]
            sid = seats.seat_of_monitor(self.app["ddc"], mon) if mon else None
            if mon and self.cfg["launch"]["return_to_menu"]:
                try:
                    await self.app["ddc"].switch_to_gpu(mon, seat_gpu)
                    seats.set(sid, shows="menu")
                except Exception as e:
                    log.warning("return to menu failed: %s", e)
            elif sid and seats.get(sid)["shows"] == vmid:
                seats.set(sid, shows="menu")   # whatever the monitor shows, that system is gone

    async def watch_loop(self):
        """When a VM on a menu monitor's GPU stops, give the monitor back to the menu."""
        turn = 0
        while True:
            await asyncio.sleep(4)
            turn += 1
            try:
                if turn % self.ADOPT_EVERY == 0:
                    await self.adopt()
                if self.watch:
                    await self.give_back()
            except Exception as e:
                log.debug("watch: %s", e)
