"""Monitor input switching over DDC/CI (VCP feature 0x60)."""

import re

from .util import log, run


class DDC:
    def __init__(self, monitors):
        self.monitors = monitors
        self._bus = {}

    async def bus(self, mon_id):
        mon = self.monitors[mon_id]
        if str(mon.get("ddc_bus", "auto")) != "auto":
            return int(mon["ddc_bus"])
        if mon_id not in self._bus:
            out = await run("ddcutil", "detect", "--brief", timeout=40)
            buses = re.findall(r"I2C bus:\s*/dev/i2c-(\d+)", out)
            if not buses:
                raise RuntimeError("DDC: монітор не знайдено")
            self._bus[mon_id] = int(buses[0])
        return self._bus[mon_id]

    async def current_input(self, mon_id):
        out = await run("ddcutil", "-b", str(await self.bus(mon_id)), "getvcp", "60", "--brief", timeout=15)
        m = re.search(r"x([0-9a-fA-F]+)\s*$", out.strip())
        return int(m.group(1), 16) if m else None

    async def switch_to_gpu(self, mon_id, pci):
        code = self.monitors[mon_id]["inputs"].get(pci)
        if code is None:
            return False
        bus = await self.bus(mon_id)
        log.info("DDC: monitor %s -> input 0x%02x (%s)", mon_id, code, pci)
        await run("ddcutil", "-b", str(bus), "setvcp", "60", f"0x{code:02x}", timeout=15)
        return True

    def monitor_for_gpu(self, pci):
        for mid, mon in self.monitors.items():
            if pci in mon["inputs"]:
                return mid
        return None
