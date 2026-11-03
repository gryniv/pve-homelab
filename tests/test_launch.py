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
    a, b = await asyncio.gather(L.launch(ticket, "igpu", ubuntu["vmid"], gpu), L.launch(ticket, "igpu", fedora["vmid"], gpu))
    ja, jb = await _wait(client, a.id), await _wait(client, b.id)
    assert ja["error"] is None
    assert jb["error"] and str(ubuntu["vmid"]) in jb["error"]
    running = [v for v in (ubuntu["vmid"], fedora["vmid"]) if demo.WORLD[v]["status"] == "running"]
    assert running == [ubuntu["vmid"]]
