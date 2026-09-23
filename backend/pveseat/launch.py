"""Starting a system on a GPU wired to the monitor the user is looking at."""

import asyncio
import itertools
import re

from . import gpus as G
from .pve import PVEError
from .util import log, run

_job_ids = itertools.count(1)


class Job:
    def __init__(self, steps):
        self.id = next(_job_ids)
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
            gpu_list = [G.gpu_of(self._addr(v)) for k, v in conf.items() if k.startswith("hostpci")]
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

    @staticmethod
    def _addr(val):
        a = val.split(",")[0].replace("host=", "").split(";")[0]
        return a if a.count(":") == 2 else "0000:" + a

    async def options(self, seat_id, vm):
        """GPUs the user could start `vm` on from this seat."""
        seat = self.cfg["seats"][seat_id]
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
                    opt["disabled"] = "система вже працює на іншій відеокарті"
            elif busy_vm:
                opt["disabled"] = f"зайнята VM {busy_vm}"
            elif vm.get("suspended") and pci not in vm["gpus"]:
                opt["disabled"] = "система приспана на диск, відеокарту їй зараз змінити не можна"
            elif not self.cfg["launch"]["assign_gpu"] and pci not in vm["gpus"]:
                opt["disabled"] = "VM налаштована на іншу відеокарту"
            opts.append(opt)
        return opts

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
            raise PVEError(404, "Систему не знайдено")
        opts = {o["pci"]: o for o in await self.options(seat_id, vm)}
        opt = opts.get(gpu)
        if not opt:
            raise PVEError(400, "Ця відеокарта не підключена до твого монітора")
        seat_gpu = self.cfg["seats"][seat_id]["gpu"]
        mon = self.app["ddc"].monitor_for_gpu(seat_gpu)

        if opt["mode"] == "virgl":
            return await self._launch_virgl(t, vm, opt)

        if vm["status"] == "running":
            if gpu not in vm["gpus"]:
                raise PVEError(409, "Система вже працює на іншій відеокарті")

            async def switch(job):
                job.step(0)
                await self.app["ddc"].switch_to_gpu(mon, gpu)
                self.watch[vmid] = (mon, seat_gpu)
            return self.start_job(switch, [f"Перемикаю монітор на {opt['name']}"])

        if opt["disabled"]:
            raise PVEError(409, f"{opt['name']}: {opt['disabled']}")
        if not await pve.can(t, f"/vms/{vmid}", "VM.PowerMgmt"):
            raise PVEError(403, "Недостатньо прав, щоб запускати цю систему")
        need_assign = gpu not in vm["gpus"]
        if need_assign and not await pve.can(t, f"/vms/{vmid}", "VM.Config.HWType"):
            raise PVEError(403, "Недостатньо прав, щоб змінити відеокарту цієї системи")

        steps = []
        if need_assign:
            steps.append(f"Призначаю {opt['name']} системі {vm['name']}")
        steps += [f"Стартую {vm['name']} (VM {vmid})", f"Перемикаю монітор на {opt['name']}"]

        async def go(job):
            i = 0
            if need_assign:
                job.step(i)
                await self._assign_gpu(vmid, gpu)
                i += 1
            job.step(i)
            upid = await pve.post(t, f"/nodes/{node}/qemu/{vmid}/status/start")
            await pve.wait_task(t, node, upid, timeout=180)
            i += 1
            job.step(i)
            await asyncio.sleep(2)
            if mon:
                await self.app["ddc"].switch_to_gpu(mon, gpu)
            self.watch[vmid] = (mon, seat_gpu)
        return self.start_job(go, steps)

    async def _launch_virgl(self, t, vm, opt):
        """Run the VM on the seat's own GPU via VirGL and show it inside the menu (noVNC)."""
        pve, node, vmid = self.app["pve"], self.cfg["node"], vm["vmid"]
        if opt["disabled"]:
            raise PVEError(409, f"{opt['name']}: {opt['disabled']}")
        if vm["status"] == "running":
            async def show(job):
                job.step(0)
                job.result = {"console": vmid}
            return self.start_job(show, [f"Відкриваю екран {vm['name']}"])

        if not await pve.can(t, f"/vms/{vmid}", "VM.PowerMgmt"):
            raise PVEError(403, "Недостатньо прав, щоб запускати цю систему")
        # A hibernated VM must wake up with the hardware it slept with.
        reconfigure = not vm["suspended"] and (vm["vga"] != "virtio-gl" or vm["gpus"])
        if reconfigure and not await pve.can(t, f"/vms/{vmid}", "VM.Config.HWType"):
            raise PVEError(403, "Недостатньо прав, щоб змінити відеоадаптер цієї системи")

        steps = []
        if reconfigure:
            steps.append(f"Вмикаю 3D через {opt['name']} (VirGL)")
        steps += [f"{'Розбуджую' if vm['suspended'] else 'Стартую'} {vm['name']} (VM {vmid})", "Відкриваю екран системи"]

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
        drop = [f"hostpci{m.group(1)}" for m in re.finditer(r"^hostpci(\d+):\s*(.*)$", conf, re.M)
                if G.gpu_of(self._addr(m.group(2))) in display]
        if drop:
            args += ["--delete", ",".join(drop)]
        log.info("VM %s -> VirGL %s", vmid, " ".join(args[3:]))
        await run(*args)

    async def _assign_gpu(self, vmid, gpu):
        """Point the VM's display-GPU hostpci entry at `gpu` (other passthrough stays)."""
        conf = await run("qm", "config", str(vmid))
        display = {g["pci"] for g in await G.list_gpus(set())}
        slot, free = None, None
        used = set()
        for line in conf.splitlines():
            m = re.match(r"hostpci(\d+):\s*(.*)", line)
            if not m:
                continue
            used.add(int(m.group(1)))
            if G.gpu_of(self._addr(m.group(2))) in display:
                slot = int(m.group(1))
        if slot is None:
            free = next(i for i in range(16) if i not in used)
        target = gpu.rsplit(".", 1)[0]  # whole device: VGA + its audio function
        log.info("VM %s: hostpci%s -> %s", vmid, slot if slot is not None else free, target)
        await run("qm", "set", str(vmid), f"--hostpci{slot if slot is not None else free}", f"{target},pcie=1")

    async def watch_loop(self):
        """When a launched VM stops, give the monitor back to the menu."""
        while True:
            await asyncio.sleep(4)
            if not self.watch:
                continue
            try:
                running = await self.app["running"](fresh=True)
            except Exception:
                continue
            for vmid, (mon, seat_gpu) in list(self.watch.items()):
                if vmid in running:
                    continue
                del self.watch[vmid]
                if mon and self.cfg["launch"]["return_to_menu"]:
                    try:
                        await self.app["ddc"].switch_to_gpu(mon, seat_gpu)
                    except Exception as e:
                        log.warning("return to menu failed: %s", e)
