"""Live host metrics read straight from /proc and /sys (cheap, no API calls)."""

import asyncio
import glob
import os
import time
from collections import deque


class HostStats:
    def __init__(self, bridge=None):
        self.bridge = bridge or self._default_iface()
        self.cpu_hist = deque(maxlen=90)  # 90 x 20 s = 30 min
        self._cpu_prev = self._read_cpu()
        self._net_prev = (time.monotonic(), self._read_net())
        self.cpu = 0.0
        self.net = (0.0, 0.0)
        self._temp_path = self._find_temp()

    @staticmethod
    def _default_iface():
        """Interface of the default route (vmbr0 on a stock Proxmox install)."""
        try:
            with open("/proc/net/route") as f:
                for line in f.readlines()[1:]:
                    p = line.split()
                    if p[1] == "00000000":
                        return p[0]
        except OSError:
            pass
        return "vmbr0"

    @staticmethod
    def _read_cpu():
        with open("/proc/stat") as f:
            v = list(map(int, f.readline().split()[1:]))
        idle = v[3] + v[4]
        return sum(v), idle

    def _read_net(self):
        with open("/proc/net/dev") as f:
            for line in f:
                if line.strip().startswith(self.bridge + ":"):
                    p = line.split(":", 1)[1].split()
                    return int(p[0]), int(p[8])
        return 0, 0

    @staticmethod
    def _find_temp():
        for name_file in glob.glob("/sys/class/hwmon/hwmon*/name"):
            with open(name_file) as f:
                if f.read().strip() in ("k10temp", "coretemp", "zenpower"):
                    return os.path.join(os.path.dirname(name_file), "temp1_input")
        return None

    def sample(self):
        tot, idle = self._read_cpu()
        pt, pi = self._cpu_prev
        self._cpu_prev = (tot, idle)
        if tot > pt:
            self.cpu = round(100 * (1 - (idle - pi) / (tot - pt)), 1)
        now, (rx, tx) = time.monotonic(), self._read_net()
        (pt_, (prx, ptx)) = self._net_prev
        dt = max(now - pt_, 0.001)
        self.net = ((rx - prx) * 8 / dt / 1e6, (tx - ptx) * 8 / dt / 1e6)
        self._net_prev = (now, (rx, tx))

    async def loop(self):
        n = 0
        while True:
            self.sample()
            if n % 4 == 0:
                self.cpu_hist.append(self.cpu)
            n += 1
            await asyncio.sleep(5)

    def snapshot(self):
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) * 1024
        temp = None
        if self._temp_path:
            try:
                with open(self._temp_path) as f:
                    temp = round(int(f.read()) / 1000)
            except OSError:
                pass
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
        return {
            "cpu": self.cpu,
            "cpu_hist": list(self.cpu_hist),
            "cores": os.cpu_count(),
            "mem_total": mem["MemTotal"],
            "mem_used": mem["MemTotal"] - mem["MemAvailable"],
            "temp": temp,
            "uptime": uptime,
            "net_rx_mbit": round(self.net[0], 1),
            "net_tx_mbit": round(self.net[1], 1),
            "load": os.getloadavg()[0],
        }
