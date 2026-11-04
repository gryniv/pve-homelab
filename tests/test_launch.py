import asyncio
import os
import time

import pytest

from pvehomelab import demo
from pvehomelab import launch as L_mod
from pvehomelab.launch import pci_addr, plan_hostpci

from conftest import login

RTX = "0000:01:00.0"
DISPLAY = {RTX, "0000:00:02.0"}


# ---------- plan_hostpci: pure ----------
def test_new_slot_when_no_display_gpu():
    conf = "name: x\nhostpci0: 0000:05:00.0,pcie=1\n"
    assert plan_hostpci(conf, DISPLAY, RTX, None, {}) == (1, "0000:01:00,pcie=1", None)


def test_replaces_display_gpu_and_keeps_options():
    conf = "hostpci0: 0000:05:00.0\nhostpci1: 0000:00:02,x-vga=1,romfile=vbios.rom,pcie=1\n"
    slot, value, old = plan_hostpci(conf, DISPLAY, RTX, None, {})
    assert slot == 1
    assert value == "0000:01:00,x-vga=1,romfile=vbios.rom,pcie=1"
    assert old == "0000:00:02,x-vga=1,romfile=vbios.rom,pcie=1"


def test_adds_pcie_only_when_missing():
    _, value, _ = plan_hostpci("hostpci0: 00:02.0,x-vga=1\n", DISPLAY, RTX, None, {})
    assert value == "0000:01:00,x-vga=1,pcie=1"
    _, value, _ = plan_hostpci("hostpci0: 00:02.0,pcie=0\n", DISPLAY, RTX, None, {})
    assert value == "0000:01:00,pcie=0"


def test_first_free_slot():
    conf = "hostpci0: 0000:05:00.0\nhostpci2: 0000:06:00.0\n"
    assert plan_hostpci(conf, DISPLAY, RTX, None, {})[0] == 1


@pytest.mark.parametrize("val,addr", [
    ("0000:01:00.0", "0000:01:00.0"),
    ("01:00", "0000:01:00"),
    ("host=01:00.0;01:00.1,x-vga=1", "0000:01:00.0"),
])
def test_pci_addr(val, addr):
    assert pci_addr(val) == addr


# ---------- launching through the demo ----------
async def _system(client, name):
    systems = await (await client.get("/api/systems", headers={"X-Seat": "igpu"})).json()
    return next(s for s in systems if s["name"] == name)


async def _wait(client, job_id, timeout=10):
    for _ in range(int(timeout / 0.2)):
        j = await (await client.get(f"/api/jobs/{job_id}")).json()
        if j["done"]:
            return j
        await asyncio.sleep(0.2)
    raise AssertionError("job did not finish")


async def _launch(client, vmid, gpu):
    r = await client.post("/api/launch", json={"vmid": vmid, "gpu": gpu}, headers={"X-Seat": "igpu"})
    assert r.status == 200, await r.text()
    return (await r.json())["id"]


async def test_launch_assigns_starts_and_watches(client):
    await login(client)
    vm = await _system(client, "ubuntu-desktop")
    gpu = next(o["pci"] for o in vm["options"] if o["mode"] == "passthrough")
    j = await _wait(client, await _launch(client, vm["vmid"], gpu))
    assert j["error"] is None
    assert demo.WORLD[vm["vmid"]]["status"] == "running"
    assert demo.WORLD[vm["vmid"]]["hostpci"] == {0: "mapping=rtx,pcie=1"}   # the RTX has a mapping: a new entry uses it


async def test_failed_start_puts_gpu_back(client):
    await login(client)
    vm = await _system(client, "ubuntu-desktop")
    before = dict(demo.WORLD[vm["vmid"]]["hostpci"])
    gpu = next(o["pci"] for o in vm["options"] if o["mode"] == "passthrough")
    demo.STATE["fail"] = "start"
    j = await _wait(client, await _launch(client, vm["vmid"], gpu))
    assert j["error"]
    assert demo.WORLD[vm["vmid"]]["status"] == "stopped"
    assert demo.WORLD[vm["vmid"]]["hostpci"] == before


async def test_two_launches_on_one_gpu(client):
    await login(client)
    ubuntu = await _system(client, "ubuntu-desktop")
    fedora = await _system(client, "fedora-workstation")
    gpu = next(o["pci"] for o in ubuntu["options"] if o["mode"] == "passthrough")
    # Both launches pass the dialog's checks before either job runs; only one may start.
    L = client.server.app["launcher"]
    ticket = next(iter(client.server.app["sessions"].values()))["ticket"]
    a, b = await asyncio.gather(L.launch(ticket, "igpu", ubuntu["vmid"], gpu),
                                L.launch(ticket, "igpu", fedora["vmid"], gpu), return_exceptions=True)
    ja = await _wait(client, a.id)
    assert ja["error"] is None
    # The second one is refused either up front (the GPU already looks busy) or by its job.
    if isinstance(b, Exception):
        assert getattr(b, "status", None) == 409
    else:
        jb = await _wait(client, b.id)
        assert jb["error"] and str(ubuntu["vmid"]) in jb["error"]
    running = [v for v in (ubuntu["vmid"], fedora["vmid"]) if demo.WORLD[v]["status"] == "running"]
    assert running == [ubuntu["vmid"]]


# ---------- PVE 8+ resource mappings: hostpciN: mapping=<name> ----------
MAPPINGS_CFG = """rtx
\tmap id=10de:2786,iommugroup=14,node=pve,path=0000:01:00,subsystem-id=1043:8863
\tmap id=10de:2786,iommugroup=3,node=pve2,path=0000:41:00
\tdescription the gaming card

igpu
\tmap id=8086:a780,node=pve,path=0000:00:02.0
"""


def test_parse_pci_mappings():
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    assert m["rtx"] == [{"node": "pve", "path": "0000:01:00"}, {"node": "pve2", "path": "0000:41:00"}]
    assert m["igpu"] == [{"node": "pve", "path": "0000:00:02.0"}]


def test_mapping_resolved_per_node():
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    assert pci_addr("mapping=rtx,pcie=1,x-vga=1", "pve", m) == "0000:01:00"
    assert pci_addr("mapping=rtx,pcie=1", "pve2", m) == "0000:41:00"
    assert pci_addr("mapping=igpu", "other", m) == "0000:00:02.0"   # one entry: used whatever the node
    assert pci_addr("mapping=missing", "pve", m) == ""


def test_plan_hostpci_over_a_mapping():
    """A VM that names a mapping keeps naming one: the new GPU's mapping, with the entry's options."""
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    conf = "hostpci0: mapping=igpu,pcie=1,x-vga=1\n"
    slot, value, old = plan_hostpci(conf, DISPLAY, RTX, "pve", m)
    assert (slot, value, old) == (0, "mapping=rtx,pcie=1,x-vga=1", "mapping=igpu,pcie=1,x-vga=1")


def test_plan_hostpci_keeps_the_form_of_the_entry():
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    # a raw address stays raw, though the RTX has a mapping
    assert plan_hostpci("hostpci0: 0000:00:02.0,x-vga=1\n", DISPLAY, RTX, "pve", m)[1] == "0000:01:00,x-vga=1,pcie=1"
    # a mapping, but none for the new GPU: its address
    other = "0000:05:00.0"
    assert plan_hostpci("hostpci0: mapping=rtx,x-vga=1\n", DISPLAY | {other}, other, "pve", m)[1] == "0000:05:00,x-vga=1,pcie=1"
    # a new entry uses the GPU's mapping when there is one, on this node
    assert plan_hostpci("", DISPLAY, RTX, "pve", m)[1] == "mapping=rtx,pcie=1"
    assert plan_hostpci("", DISPLAY, RTX, "pve3", {"rtx": m["rtx"]})[1] == "0000:01:00,pcie=1"


def test_plan_hostpci_brings_back_what_virgl_took_out():
    conf = "hostpci0: 0000:05:00.0\n"
    remembered = {2: "mapping=igpu,pcie=1,x-vga=1,romfile=gpu.rom"}
    slot, value, old = plan_hostpci(conf, DISPLAY, RTX, "pve", {}, remembered)
    assert (slot, value, old) == (2, "0000:01:00,pcie=1,x-vga=1,romfile=gpu.rom", None)


def test_mapping_for():
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    assert gpus.mapping_for(RTX, "pve", m) == "rtx"
    assert gpus.mapping_for("0000:41:00.0", "pve2", m) == "rtx"
    assert gpus.mapping_for("0000:00:02.0", "pve", m) == "igpu"       # a mapping of function 0
    assert gpus.mapping_for("0000:05:00.0", "pve", m) is None


def test_vm_gpus_sees_mapped_cards(monkeypatch):
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    confs = {"/etc/pve/qemu-server/102.conf": "hostpci0: mapping=rtx,pcie=1\nhostpci1: 0000:79:00.6\n[snap]\nhostpci0: 0000:09:00\n",
             "/etc/pve/qemu-server/103.conf": "hostpci0: host=0000:05:00.0;0000:05:00.1\n"}
    monkeypatch.setattr(gpus.glob, "glob", lambda pattern: list(confs))
    monkeypatch.setattr(gpus, "_read", lambda path, default="": confs.get(path, default))
    monkeypatch.setattr(gpus, "pci_mappings", lambda: m)
    monkeypatch.setattr(gpus, "local_node", lambda: "pve")
    used = gpus.vm_gpus()
    assert used["0000:01:00"] == [102] and used["0000:79:00.6"] == [102]
    assert "0000:09:00" not in used                       # snapshot sections don't count
    assert used["0000:05:00.0"] == [103] and used["0000:05:00.1"] == [103]


async def test_a_vm_started_outside_the_menu_gives_the_monitor_back(client, monkeypatch):
    """Started from Proxmox while the menu runs: the menu picks it up, and when it stops the monitor
    goes back to the menu (it used to stay on that GPU's input, with no picture)."""
    from pvehomelab.ddc import DDC
    await login(client)
    app = client.server.app
    L, switched = app["launcher"], []
    monkeypatch.setitem(app["cfg"]["seats"]["igpu"], "kiosk", True)   # the menu is on that monitor, as on a host

    async def switch(self, mon, pci):
        switched.append((mon, pci))
        return True
    monkeypatch.setattr(DDC, "switch_to_gpu", switch)
    vm = await _system(client, "ubuntu-desktop")
    gpu = next(o["pci"] for o in vm["options"] if o["mode"] == "passthrough")
    demo.WORLD[vm["vmid"]].update(hostpci={0: f"{gpu.rsplit('.', 1)[0]},pcie=1"}, status="running",
                                  started=time.time() - 3600)   # as Proxmox would, an hour ago
    app["resources"].invalidate()
    assert vm["vmid"] not in L.watch
    await L.adopt()
    seat_gpu = app["cfg"]["seats"]["igpu"]["gpu"]
    mon = app["ddc"].monitor_for_gpu(seat_gpu)
    assert L.watch[vm["vmid"]] == (mon, seat_gpu)
    await L.give_back()
    assert switched == [] and vm["vmid"] in L.watch            # still running: nothing happens
    demo.WORLD[vm["vmid"]]["status"] = "stopped"
    await L.give_back()
    assert switched == [(mon, seat_gpu)] and vm["vmid"] not in L.watch


# ---------- VirGL and back: the GPU entry keeps what it said ----------
async def _ticket(client):
    return next(iter(client.server.app["sessions"].values()))["ticket"]


async def test_virgl_and_back_restores_the_gpu_entry(client):
    """VM 102 names the RTX mapping with x-vga. Going to VirGL takes the entry out; the next start on
    the RTX puts the same entry and display back (it used to come back as a bare address)."""
    await login(client)
    L = client.server.app["launcher"]
    g = demo.WORLD[102]
    await L._to_virgl(102)
    assert g["hostpci"] == {} and g["vga"].startswith("virtio-gl")
    assert L_mod.remembered(102) == {"hostpci": {0: "mapping=rtx,pcie=1,x-vga=1"}, "vga": "std"}
    await L._to_virgl(102)                                     # again: what was kept stays
    assert L_mod.remembered(102)["vga"] == "std"
    undo = await L._assign_gpu(102, RTX, await _ticket(client))
    assert g["hostpci"] == {0: "mapping=rtx,pcie=1,x-vga=1"} and g["vga"] == "std"
    await L._undo_assign(102, undo)                            # a start that failed: VirGL as it was
    assert g["hostpci"] == {} and g["vga"].startswith("virtio-gl")


async def test_launch_after_virgl_forgets_what_it_kept(client):
    await login(client)
    L = client.server.app["launcher"]
    await L._to_virgl(102)
    vm = await _system(client, "win11-gaming")
    j = await _wait(client, await _launch(client, 102, RTX))
    assert j["error"] is None, j
    assert demo.WORLD[102]["hostpci"] == {0: "mapping=rtx,pcie=1,x-vga=1"}
    assert not os.path.exists(L_mod._remembered_path(102))
    assert vm["vmid"] == 102


async def test_writing_a_mapping_needs_mapping_use(client):
    await login(client, "guest@pve")
    L = client.server.app["launcher"]
    demo.WORLD[100]["hostpci"] = {}
    with pytest.raises(Exception) as e:
        await L._assign_gpu(100, RTX, await _ticket(client))
    assert getattr(e.value, "status", None) == 403 and "rtx" in str(e.value)
    assert demo.WORLD[100]["hostpci"] == {}


# ---------- a VM that starts without the menu gets the monitor ----------
@pytest.mark.parametrize("follow,host_up,vm_age,moves", [
    ("boot", 120, 30, True),          # an onboot VM while the host boots
    ("boot", 7200, 30, False),        # started from Proxmox later: only watched
    ("always", 7200, 30, True),
    ("always", 7200, 3600, False),    # up for an hour: the menu just restarted
    ("never", 120, 30, False),
])
async def test_follow_start(client, monkeypatch, follow, host_up, vm_age, moves):
    from pvehomelab.ddc import DDC
    await login(client)
    app = client.server.app
    L, switched = app["launcher"], []
    monkeypatch.setitem(app["cfg"]["seats"]["igpu"], "kiosk", True)
    monkeypatch.setitem(app["cfg"]["launch"], "follow_start", follow)
    monkeypatch.setattr(L_mod, "host_uptime", lambda: host_up)

    async def switch(self, mon, pci):
        switched.append(pci)
        return True
    monkeypatch.setattr(DDC, "switch_to_gpu", switch)
    demo.WORLD[102].update(status="running", started=time.time() - vm_age)
    app["resources"].invalidate()
    await L.adopt()
    assert 102 in L.watch
    assert switched == ([RTX] if moves else [])
