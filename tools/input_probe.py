"""The host's keyboards, mice and gamepads as the menu sees them; and a short try of lending them to a VM.

Run ON the Proxmox host, as root:
    python3 tools/input_probe.py                 # list: what each is, its evdev node, which VM has it already
    python3 tools/input_probe.py --vm 102 --try 20
        lends the keyboards and mice to VM 102 for 20 s (the VM must run), as the menu would, then takes
        them back. The hotkey (both Ctrl by default) gives them back sooner. Nothing is written to the
        VM's config; if this script is killed, stopping the VM or `qm monitor 102` -> object_del phl0 ...
"""
import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "backend"), "/opt/pve-homelab/backend"):
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break
from pvehomelab import config, inputs  # noqa: E402


async def main(a):
    cfg = config.load()
    node = cfg["node"]
    units = inputs.host_units(node)
    for u in units:
        where = f"VM {u['in_vm']} has it of its own" if u["in_vm"] else "free"
        usb = f"usb bus {u['usb']['bus']} port {u['usb']['port']} ({u['usb']['id']})" if u["usb"] else "not USB"
        print(f"{u['id']:<20} {u['name']:<34} {'+'.join(u['kinds']):<16} {usb:<36} {where}")
        for ev in u["evdev"]:
            print(f"{'':<20}   {ev['kind']:<9} {ev['path']}  grabbed={inputs.grabbed(ev['path'])}")
    if not a.vm:
        return 0
    hotkey = (cfg.get("input") or {}).get("hotkey", "ctrl-ctrl")
    objs = []
    for u in units:
        if u["in_vm"]:
            continue
        for ev in u["evdev"]:
            if ev["kind"] == "pad":
                continue
            oid = f"phl{len(objs)}"
            opts = f"input-linux,id={oid},evdev={inputs.hmp(ev['path'])}"
            if ev["kind"] == "keyboard":
                opts += f",grab_all=on,repeat=on,grab-toggle={hotkey}"
            print(f"object_add {opts}:", (await inputs.monitor(node, a.vm, f"object_add {opts}")).strip() or "ok")
            objs.append((oid, ev))
    kbs = [ev["path"] for _, ev in objs if ev["kind"] == "keyboard"]
    end = time.monotonic() + a.try_seconds
    await asyncio.sleep(1)
    while time.monotonic() < end:
        if kbs and not any(inputs.grabbed(p) for p in kbs):
            print("the keyboard came back (hotkey)")
            break
        await asyncio.sleep(0.25)
    for oid, _ in objs:
        print(f"object_del {oid}:", (await inputs.monitor(node, a.vm, f"object_del {oid}")).strip() or "ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vm", type=int)
    ap.add_argument("--try", dest="try_seconds", type=int, default=20)
    sys.exit(asyncio.run(main(ap.parse_args())))
