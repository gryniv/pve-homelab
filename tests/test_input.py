"""The keyboard, mouse and gamepads of a screen go into a system with its monitor, and come back."""

import asyncio

import pytest

from pvehomelab import demo, inputs

from conftest import login

# the demo replaces these once an app is made: keep the real ones from collection time
REAL_UNITS = inputs.units
REAL_PARSE = inputs.parse_devices


def _units():
    return REAL_UNITS(REAL_PARSE(demo.INPUT_DEVICES), demo.INPUT_LINKS, {102: "usb0: host=046d:c534\n"}, "demo", {})


def test_devices_are_grouped_by_what_they_hang_off():
    u = {x["id"]: x for x in _units()}
    assert u["1-3"]["kinds"] == ["keyboard", "mouse"] and u["1-3"]["usb"] == {"bus": 1, "port": "3", "id": "046d:c52b"}
    assert [e["path"] for e in u["1-3"]["evdev"]] == [demo.INPUT_LINKS["event5"], demo.INPUT_LINKS["event6"]]
    assert u["1-4"]["kinds"] == ["pad"]
    assert u["0005:05ac:024f"]["usb"] is None                       # Bluetooth: evdev only
    assert u["1-5"]["in_vm"] == 102                                  # VM 102's own keyboard stays its own
    assert not any("Power" in x["name"] for x in u.values())


def test_what_a_vm_already_has():
    maps = inputs.parse_usb_mappings("kbd\n\tmap id=046d:c534,node=pve\nport4\n\tmap path=1-4,node=pve\n")
    conf = "usb0: mapping=kbd\nusb1: host=2-1.3,usb3=1\nusb2: mapping=port4\nusb3: host=1a2b:3c4d\n"
    ids, ports = inputs.vm_usb(conf, "pve", maps)
    assert ids == {"046d:c534", "1a2b:3c4d"} and ports == {"2-1.3", "1-4"}


def test_hmp_values_double_their_commas():
    assert inputs.hmp("/dev/input/by-id/a,b") == "/dev/input/by-id/a,,b"


async def _launch_ubuntu(client, **extra):
    systems = await (await client.get("/api/systems", headers={"X-Seat": "igpu"})).json()
    vm = next(s for s in systems if s["name"] == "ubuntu-desktop")
    gpu = next(o["pci"] for o in vm["options"] if o["mode"] == "passthrough")
    r = await client.post("/api/launch", json={"vmid": vm["vmid"], "gpu": gpu, **extra}, headers={"X-Seat": "igpu"})
    assert r.status == 200, await r.text()
    jid = (await r.json())["id"]
    for _ in range(60):
        j = await (await client.get(f"/api/jobs/{jid}")).json()
        if j["done"]:
            return vm["vmid"], j
        await asyncio.sleep(0.2)
    raise AssertionError("job did not finish")


async def test_input_goes_with_the_monitor_and_comes_back(client):
    await login(client)
    app = client.server.app
    vmid, j = await _launch_ubuntu(client, input=True)
    assert j["error"] is None and len(j["steps"]) == 4
    cmds = [c for v, c in demo.QEMU_LOG if v == vmid]
    assert any(c.startswith("object_add input-linux,id=phl0,evdev=/dev/input/by-id/usb-Logitech_USB_Receiver-event-kbd,grab_all=on,repeat=on,grab-toggle=ctrl-ctrl") for c in cmds)
    assert any(c.startswith("object_add input-linux,id=phl1,evdev=") and "mouse" in c for c in cmds)
    assert any(c.startswith("device_add usb-host,hostbus=1,hostport=4,id=phlpad0") for c in cmds)
    assert any("event9" in c for c in cmds)                                    # the Bluetooth keyboard, by evdev
    assert not any("c534" in c or "1-5" in c for c in cmds)                   # never the VM's own
    assert app["seats"].get("igpu") == {**app["seats"].get("igpu"), "shows": vmid, "input": vmid}
    # both Ctrl in the VM: QEMU lets go, the menu takes it all back with the monitor
    await client.post("/api/demo/input-release")
    for _ in range(30):
        if app["seats"].get("igpu")["shows"] == "menu":
            break
        await asyncio.sleep(0.2)
    assert app["seats"].get("igpu")["shows"] == "menu" and app["seats"].get("igpu")["input"] == "menu"
    cmds = [c for v, c in demo.QEMU_LOG if v == vmid]
    assert "object_del phl0" in cmds and "device_del phlpad0" in cmds
    assert vmid not in app["input"].given


async def test_no_input_without_the_console_right_or_when_off(client, monkeypatch):
    await login(client)
    monkeypatch.setitem(client.server.app["cfg"]["input"], "mode", "off")
    vmid, j = await _launch_ubuntu(client, input=True)
    assert len(j["steps"]) == 3 and not [c for v, c in demo.QEMU_LOG if v == vmid]


async def test_a_stopped_vm_takes_nothing_back(client):
    await login(client)
    app = client.server.app
    vmid, _ = await _launch_ubuntu(client, input=True)
    demo.WORLD[vmid]["status"] = "stopped"
    app["resources"].invalidate()
    await app["launcher"].give_back()
    assert vmid not in app["input"].given and app["seats"].get("igpu")["input"] == "menu"


async def test_the_device_list(client):
    await login(client)
    d = await (await client.get("/api/input")).json()
    ids = {u["id"]: u for u in d["units"]}
    assert d["mode"] == "evdev" and ids["1-5"]["in_vm"] == 102 and ids["1-3"]["chosen"]


async def test_the_menu_asked_back_any_way_takes_the_keyboard_too(client):
    await login(client)
    app = client.server.app
    vmid, _ = await _launch_ubuntu(client, input=True)
    r = await client.post("/api/seat/focus", json={"to": "menu"}, headers={"X-Seat": "igpu"})
    assert r.status == 200 and vmid not in app["input"].given
    assert "object_del phl0" in [c for v, c in demo.QEMU_LOG if v == vmid]
    # back to the system: the keyboard goes with it again (the person's launch.pass_input)
    r = await client.post("/api/seat/focus", json={"to": vmid}, headers={"X-Seat": "igpu"})
    assert r.status == 200 and vmid in app["input"].given
