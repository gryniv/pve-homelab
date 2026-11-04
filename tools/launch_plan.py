"""What the menu would do to start a VM from a seat, on the real host, changing nothing.

Run ON the Proxmox host, as root:
    python3 tools/launch_plan.py [VMID] [--seat igpu]
Reads `qm list`, `qm config`, sysfs and the monitor over DDC (ddcutil detect / getvcp 60, both
read-only), then prints the GPUs, the options the launch dialog would offer, the `qm set` it would
run (and the one that undoes it if the start fails) and the input it would switch the monitor to.
Nothing is started, assigned or switched (tools/dryrun.py skips those steps instead of planning them).
"""
import argparse
import asyncio
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "backend"), "/opt/pve-homelab/backend"):
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break
from pvehomelab import config, ddc as D, gpus as G, launch as L  # noqa: E402


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60).stdout


async def main(VMID, seat_id):
    cfg = config.load()
    node = cfg["node"]
    running = {int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\s+\S+\s+running", sh("qm", "list"), re.M)}
    gpus = await G.list_gpus(running)
    print("== GPUs (sysfs)")
    for g in gpus:
        print(f"  {g['pci']} {g['name']!r} vendor={g['vendor']} driver={g['driver']} integrated={g['integrated']} "
              f"assigned={g['assigned_vms']} running_vm={g['running_vm']} connectors={g['connectors']}")
    seat = cfg["seats"][seat_id]
    ddc = D.DDC(cfg["monitors"])
    mon = ddc.monitor_for_gpu(seat["gpu"])
    wired = list(cfg["monitors"][mon]["inputs"]) if mon else []
    print(f"== seat {seat_id}: gpu={seat['gpu']} monitor={mon} wired={wired} launch={cfg['launch']}")
    conf = sh("qm", "config", str(VMID))
    print(f"== VM {VMID} hostpci/vga now:")
    for line in conf.splitlines():
        if line.startswith(("hostpci", "vga", "name", "machine", "bios")):
            print("  " + line)
    display = {g["pci"] for g in await G.list_gpus(set())}
    vm_gpus = [L.pci_addr(m.group(2), node) for m in L.HOSTPCI.finditer(conf)]
    print(f"== VM {VMID} display GPUs now: {[a for a in vm_gpus if G.gpu_of(a or '-') in display]}")
    for pci in wired:
        if pci == seat["gpu"] and not cfg["launch"]["allow_igpu"]:
            print(f"== option {pci}: VirGL inside the menu (the seat's own GPU); would run qm set --vga virtio-gl,memory=256 + drop display hostpci"
                  f" (kept in {L._remembered_path(VMID)} to put back on the next start on a passed-through GPU)")
            continue
        g = next((x for x in gpus if x["pci"] == pci), None)
        if not g:
            print(f"== option {pci}: not on this host (sysfs) — the dialog would leave it out")
            continue
        busy = g["running_vm"] not in (None, VMID)
        need = pci not in [G.gpu_of(a or '-') for a in vm_gpus]
        print(f"== option {pci} ({g['name']}): busy_by={g['running_vm'] if busy else None} needs_assign={need}")
        if need:
            back = L.remembered(VMID)
            slot, value, old = L.plan_hostpci(conf, display, pci, node, remembered=back["hostpci"])
            print(f"   would run: qm set {VMID} --hostpci{slot} {value}   (was: {old or 'nothing'})")
            if back["hostpci"] or back["vga"] is not None:
                print(f"   kept from the last switch to VirGL: {back} (its options and display come back)")
            if value.startswith("mapping="):
                print(f"   writes a resource mapping: the user needs Mapping.Use on /mapping/pci/{value.split(',')[0][8:]}")
            print(f"   undo if start fails: " + (f"qm set {VMID} --hostpci{slot} {old}" if old else f"qm set {VMID} --delete hostpci{slot}"))
        code = cfg["monitors"][mon]["inputs"].get(pci)
        print(f"   after start: ddcutil setvcp 60 0x{code:02x} (input for {pci}); on VM stop back to 0x{cfg['monitors'][mon]['inputs'][seat['gpu']]:02x}")
    print("== DDC (read only)")
    try:
        bus = await ddc.bus(mon)
        cur = await ddc.current_input(mon)
        names = {v: k for k, v in cfg["monitors"][mon]["inputs"].items()}
        print(f"  bus /dev/i2c-{bus}; current input 0x{cur:02x} -> {names.get(cur, 'not in config')}" if cur is not None else f"  bus {bus}; input unreadable")
    except Exception as e:
        print(f"  DDC failed: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vmid", type=int)
    ap.add_argument("--seat", default="igpu")
    a = ap.parse_args()
    asyncio.run(main(a.vmid, a.seat))
