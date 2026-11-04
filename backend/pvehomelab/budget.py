"""Time limits for systems (a child's VM, say): the hours it may run, and minutes a day.

The limit belongs to the VM, not to a person, so it holds however the VM is started: from the menu,
from Proxmox, by Wake-on-LAN. Nothing can be drawn over a passed-through GPU's picture, so a warning
takes the monitor back to the menu for a few seconds with a countdown, and gives it back. At zero
the VM is shut down; after the grace minutes, stopped.

    limits:
      102: {hours: "16:00-19:00, 10:00-12:00", daily_min: 90, grace_min: 5, exempt: "ihor@pve"}
"""

import asyncio
import json
import os
import time

from . import config
from .seats import in_window
from .util import log, pvesh_create

WARN_AT = (10, 2)        # minutes left: a warning on the monitor
SHOW_FOR = 8             # s the monitor shows the menu's countdown
USAGE = "usage.json"


def _today(now=None):
    return time.strftime("%Y-%m-%d", time.localtime(now))


def windows(hours):
    return [w.strip() for w in (hours or "").split(",") if w.strip()]


def minutes_to_window_end(hours, now=None):
    """Minutes left in the current allowed window (None: no windows set; 0: outside them all)."""
    ws = windows(hours)
    if not ws:
        return None
    now = now or time.time()
    best = 0
    t = time.localtime(now)
    cur = t.tm_hour * 60 + t.tm_min
    for w in ws:
        if not in_window(w, now):
            continue
        end = w.split("-")[1].strip()
        h, m = (int(x) for x in end.split(":"))
        left = (h * 60 + m - cur) % (24 * 60)
        best = max(best, left or 24 * 60)
    return best


class Limits:
    def __init__(self, app):
        self.app = app
        self.warned = {}        # vmid -> set of thresholds already shown today
        self.ending = {}        # vmid -> time the shutdown was asked
        self.last_tick = time.time()

    def cfg(self):
        return {int(k): v for k, v in (self.app["cfg"].get("limits") or {}).items() if str(k).isdigit()}

    # ---------- what was used today ----------
    def _path(self):
        return os.path.join(config.STATE_DIR, USAGE)

    def usage(self, now=None):
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        day = d.get(_today(now)) if isinstance(d, dict) else None
        return {int(k): float(v) for k, v in (day or {}).items()}

    def _save(self, used, now=None):
        os.makedirs(config.STATE_DIR, exist_ok=True)
        tmp = self._path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({_today(now): {str(k): round(v, 2) for k, v in used.items()}}, f)
        os.replace(tmp, self._path())

    # ---------- the rules ----------
    def left(self, vmid, now=None):
        """Minutes this VM may still run now (None: no limit)."""
        rule = self.cfg().get(vmid)
        if not rule:
            return None
        parts = []
        to_end = minutes_to_window_end(rule.get("hours"), now)
        if to_end is not None:
            parts.append(to_end)
        daily = int(rule.get("daily_min") or 0)
        if daily:
            parts.append(max(0.0, daily - self.usage(now).get(vmid, 0.0)))
        return min(parts) if parts else None

    def exempt(self, vmid, user):
        rule = self.cfg().get(vmid) or {}
        return bool(user) and user in [u.strip() for u in str(rule.get("exempt") or "").split(",") if u.strip()]

    def may_start(self, vmid, user=None, now=None):
        if self.exempt(vmid, user):
            return True
        left = self.left(vmid, now)
        return left is None or left >= 1

    # ---------- the clock ----------
    async def tick(self, now=None):
        now = now or time.time()
        step = max(0.0, min(5.0, (now - self.last_tick) / 60))
        self.last_tick = now
        rules = self.cfg()
        if not rules:
            return
        running = await self.app["running"](fresh=True)
        used = self.usage(now)
        for vmid in rules:
            if vmid in running:
                used[vmid] = used.get(vmid, 0.0) + step
        self._save(used, now)
        for vmid in rules:
            if vmid not in running:
                self.ending.pop(vmid, None)
                continue
            left = self.left(vmid, now)
            if left is None:
                continue
            seen = self.warned.setdefault((vmid, _today(now)), set())
            for at in WARN_AT:
                if left <= at and at not in seen:
                    seen.add(at)
                    asyncio.get_running_loop().create_task(self.warn(vmid, max(0, round(left))))
            if left < 0.5:
                await self.end(vmid, rules[vmid], now)

    async def warn(self, vmid, minutes):
        """The monitor showing this VM goes to the menu for a few seconds with the minutes left."""
        seats, L = self.app["seats"], self.app["launcher"]
        for sid in seats.kiosk_seats():
            if seats.get(sid)["shows"] != vmid:
                continue
            seats.notify(sid, {"limit": {"vmid": vmid, "minutes": minutes}})
            try:
                await L.peek_menu(sid, vmid, SHOW_FOR)
            except Exception as e:
                log.info("limit warning on seat %s: %s", sid, e)
        log.info("VM %s: %s min left today", vmid, minutes)

    async def end(self, vmid, rule, now):
        node = self.app["cfg"]["node"]
        asked = self.ending.get(vmid)
        if asked is None:
            self.ending[vmid] = now
            log.info("VM %s: its time is up, shutting down", vmid)
            await pvesh_create(f"/nodes/{node}/qemu/{vmid}/status/shutdown")
        elif now - asked >= int(rule.get("grace_min") or 5) * 60:
            log.info("VM %s: still running after the grace minutes, stopping", vmid)
            await pvesh_create(f"/nodes/{node}/qemu/{vmid}/status/stop")
            self.ending[vmid] = now
        self.app["resources"].invalidate()

    async def loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self.tick()
            except Exception as e:
                log.debug("limits: %s", e)
