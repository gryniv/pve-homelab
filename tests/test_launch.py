import asyncio

import pytest

from pvehomelab import demo
from pvehomelab.launch import pci_addr, plan_hostpci

from conftest import login

RTX = "0000:01:00.0"
DISPLAY = {RTX, "0000:00:02.0"}


# ---------- plan_hostpci: pure ----------
def test_new_slot_when_no_display_gpu():
    conf = "name: x\nhostpci0: 0000:05:00.0,pcie=1\n"
    assert plan_hostpci(conf, DISPLAY, RTX) == (1, "0000:01:00,pcie=1", None)


def test_replaces_display_gpu_and_keeps_options():
    conf = "hostpci0: 0000:05:00.0\nhostpci1: 0000:00:02,x-vga=1,romfile=vbios.rom,pcie=1\n"
    slot, value, old = plan_hostpci(conf, DISPLAY, RTX)
    assert slot == 1
    assert value == "0000:01:00,x-vga=1,romfile=vbios.rom,pcie=1"
    assert old == "0000:00:02,x-vga=1,romfile=vbios.rom,pcie=1"


def test_adds_pcie_only_when_missing():
    _, value, _ = plan_hostpci("hostpci0: 00:02.0,x-vga=1\n", DISPLAY, RTX)
    assert value == "0000:01:00,x-vga=1,pcie=1"
    _, value, _ = plan_hostpci("hostpci0: 00:02.0,pcie=0\n", DISPLAY, RTX)
    assert value == "0000:01:00,pcie=0"


def test_first_free_slot():
    conf = "hostpci0: 0000:05:00.0\nhostpci2: 0000:06:00.0\n"
    assert plan_hostpci(conf, DISPLAY, RTX)[0] == 1


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
    assert demo.WORLD[vm["vmid"]]["hostpci"] == [gpu.rsplit(".", 1)[0]]


async def test_failed_start_puts_gpu_back(client):
    await login(client)
    vm = await _system(client, "ubuntu-desktop")
    before = list(demo.WORLD[vm["vmid"]]["hostpci"])
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
    from pvehomelab import gpus
    m = gpus.parse_pci_mappings(MAPPINGS_CFG)
    conf = "hostpci0: mapping=igpu,pcie=1,x-vga=1\n"
    slot, value, old = plan_hostpci(conf, DISPLAY, RTX, "pve", m)
    assert (slot, value, old) == (0, "0000:01:00,pcie=1,x-vga=1", "mapping=igpu,pcie=1,x-vga=1")


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
    demo.WORLD[vm["vmid"]].update(hostpci=[gpu.rsplit(".", 1)[0]], status="running")   # as Proxmox would
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
