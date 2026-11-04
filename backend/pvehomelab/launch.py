"""Starting a system on a GPU wired to the monitor the user is looking at."""

import asyncio
import itertools
import re
import time

from . import gpus as G
from .i18n import _
from .pve import PVEError
from .util import log, run

_job_ids = itertools.count(1)

HOSTPCI = re.compile(r"^hostpci(\d+):\s*(.*)$", re.M)


def pci_addr(val, node=None, mappings=None):
    """The (first) PCI address in a hostpciN value ("0000:01:00.0", "01:00", "host=01:00.0;01:00.1,x-vga=1",
    or a PVE resource mapping "mapping=rtx,pcie=1"); "" when a mapping can't be resolved."""
    devs = G.hostpci_devices(val, node, mappings)
    return devs[0] if devs else ""


def plan_hostpci(conf, display, gpu, node=None, mappings=None):
    """Where `gpu` goes in a VM config (text of `qm config`): the hostpci slot that already holds a
    display GPU, else the first free one. Returns (slot, new value, old value or None). The new
    value keeps the old entry's options (x-vga, romfile, rombar, ...) and only swaps the device."""
    target = gpu.rsplit(".", 1)[0]  # whole device: VGA + its audio function
    used, slot, old = set(), None, None
    for m in HOSTPCI.finditer(conf):
        n, val = int(m.group(1)), m.group(2).strip()
        used.add(n)
        if slot is None and G.gpu_of(pci_addr(val, node, mappings) or "-") in display:
            slot, old = n, val
    if slot is None:
        slot = next(i for i in range(16) if i not in used)
        return slot, f"{target},pcie=1", None
    opts = [o for o in old.split(",")[1:] if o]
    if not any(o.split("=")[0] == "pcie" for o in opts):
        opts.append("pcie=1")
    return slot, ",".join([target] + opts), old


class Job:
    def __init__(self, steps):
        self.id = next(_job_ids)
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

    async def options(self, seat_id, vm):
        """GPUs the user could start `vm` on from this seat."""
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
    def start_job(self, coro_fn, steps):
        job = Job(steps)
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

    async def launch(self, t, seat_id, vmid, gpu):
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
                await self.app["ddc"].switch_to_gpu(mon, gpu)
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
                    undo = await self._assign_gpu(vmid, gpu)
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
                i += 1
                job.step(i)
                await asyncio.sleep(2)
                if mon:
                    await self.app["ddc"].switch_to_gpu(mon, gpu)
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
        conf = await run("qm", "config", str(vmid))
        display = {g["pci"] for g in await G.list_gpus(set())}
        args = ["qm", "set", str(vmid), "--vga", "virtio-gl,memory=256"]
        drop = [f"hostpci{m.group(1)}" for m in HOSTPCI.finditer(conf)
                if G.gpu_of(pci_addr(m.group(2), self.cfg["node"]) or "-") in display]
        if drop:
            args += ["--delete", ",".join(drop)]
        log.info("VM %s -> VirGL %s", vmid, " ".join(args[3:]))
        await run(*args)

    async def _assign_gpu(self, vmid, gpu):
        """Point the VM's display-GPU hostpci entry at `gpu` (other passthrough stays).
        Returns what _undo_assign needs to put it back."""
        conf = await run("qm", "config", str(vmid))
        display = {g["pci"] for g in await G.list_gpus(set())}
        slot, value, old = plan_hostpci(conf, display, gpu, self.cfg["node"])
        log.info("VM %s: hostpci%s %s -> %s", vmid, slot, old or "(new)", value)
        await run("qm", "set", str(vmid), f"--hostpci{slot}", value)
        return (slot, old)

    async def _undo_assign(self, vmid, undo):
        slot, old = undo
        try:
            if old:
                await run("qm", "set", str(vmid), f"--hostpci{slot}", old)
            else:
                await run("qm", "set", str(vmid), "--delete", f"hostpci{slot}")
            log.info("VM %s: hostpci%s restored", vmid, slot)
        except Exception as e:
            log.warning("VM %s: could not restore hostpci%s (%s): %s", vmid, slot, old, e)

    ADOPT_EVERY = 8   # turns of the watch loop (4 s each): about every half a minute

    async def adopt(self):
        """Watch VMs that hold a GPU wired to a menu monitor though the menu did not start them:
        started before it (an update restarts the menu at night) or from Proxmox itself. Otherwise
        the monitor stays on that GPU's input, with no picture, after the VM stops."""
        cfg, ddc = self.cfg, self.app["ddc"]
        running = await self.app["running"]()
        for g in await G.list_gpus(running):
            vm, mon = g["running_vm"], ddc.monitor_for_gpu(g["pci"])
            if not vm or not mon or vm in self.watch:
                continue
            seat_gpu = next((s["gpu"] for s in cfg["seats"].values()
                             if s.get("kiosk") and s.get("gpu") and ddc.monitor_for_gpu(s["gpu"]) == mon), None)
            if seat_gpu:
                self.watch[vm] = (mon, seat_gpu)
                log.info("watching VM %s on monitor %s", vm, mon)

    async def give_back(self):
        """The watched VMs that stopped: the monitor goes back to the menu."""
        running = await self.app["running"](fresh=True)
        for vmid, (mon, seat_gpu) in list(self.watch.items()):
            if vmid in running:
                continue
            del self.watch[vmid]
            if mon and self.cfg["launch"]["return_to_menu"]:
                try:
                    await self.app["ddc"].switch_to_gpu(mon, seat_gpu)
                except Exception as e:
                    log.warning("return to menu failed: %s", e)

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
