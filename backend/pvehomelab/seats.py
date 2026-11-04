"""What each screen on the host is showing: the menu, or a system on a GPU wired to its monitor.

The launcher says so when it switches a monitor; the page of that seat listens (/api/seat/events)
and, while its monitor shows a system, stands aside ("away"): no widgets, no effects, no keys acted
on, except both Ctrl keys, which bring the monitor back to the menu.
"""

import asyncio
import re
import time

from .util import log


class Seats:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = {}
        self.listeners = {}   # seat id -> set of asyncio.Queue

    def kiosk_seats(self):
        """Seats drawn on this host's own GPUs (the "web" seat has none)."""
        return [sid for sid, s in self.cfg["seats"].items() if s.get("gpu")]

    def get(self, sid):
        return dict(self.state.get(sid) or {"shows": "menu", "input": "menu", "since": 0, "screen": "on"})

    def seat_of_monitor(self, ddc, mon):
        """The kiosk seat whose menu is on monitor `mon` (None if no menu is drawn there)."""
        return next((sid for sid in self.kiosk_seats() if ddc.monitor_for_gpu(self.cfg["seats"][sid]["gpu"]) == mon), None)

    def set(self, sid, shows=None, input=None, screen=None):
        if not sid:
            return
        cur = self.get(sid)
        new = {"shows": cur["shows"] if shows is None else shows, "input": cur["input"] if input is None else input,
               "screen": cur.get("screen", "on") if screen is None else screen}
        if new["shows"] == "menu":
            new["input"] = "menu"     # the menu on screen has the keyboard, whatever held it
        if new["shows"] != "menu":
            new["screen"] = "on"      # a system on the monitor: never dark
        if new == {k: cur.get(k) for k in ("shows", "input", "screen")}:
            return
        self.state[sid] = {**new, "since": time.time() if new["shows"] != cur["shows"] else cur["since"]}
        for q in list(self.listeners.get(sid, ())):
            q.put_nowait(self.get(sid))

    def notify(self, sid, notice):
        """Something for the page to show once (a time limit's countdown); the state stays as it is."""
        for q in list(self.listeners.get(sid, ())):
            q.put_nowait({**self.get(sid), "notice": notice})

    def subscribe(self, sid):
        q = asyncio.Queue()
        self.listeners.setdefault(sid, set()).add(q)
        return q

    def unsubscribe(self, sid, q):
        self.listeners.get(sid, set()).discard(q)


# ---------------------------------------------------------------- the monitor's power

def in_window(window, now=None):
    """Is the clock inside "23:00-07:00" (it may run past midnight)? An empty window never is."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", window or "")
    if not m:
        return False
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    t = time.localtime(now)
    cur = t.tm_hour * 60 + t.tm_min
    return a <= cur < b if a <= b else cur >= a or cur < b


class Power:
    """Monitors of the menu go dark after some time without a key, and at night (screen: in config);
    any key or touch on that screen lights them again. Never while a system is on the monitor."""

    def __init__(self, app):
        self.app = app
        self.touched = {}    # seat -> time of the last key or touch

    def cfg(self):
        return self.app["cfg"].get("screen") or {}

    def touch(self, sid):
        self.touched[sid] = time.time()

    async def wake(self, sid):
        self.touch(sid)
        seats = self.app["seats"]
        if seats.get(sid).get("screen") == "off":
            await self._set(sid, True)

    async def _set(self, sid, on):
        ddc, seats = self.app["ddc"], self.app["seats"]
        mon = ddc.monitor_for_gpu(self.app["cfg"]["seats"][sid]["gpu"])
        seats.set(sid, screen="on" if on else "off")   # the page darkens itself too: a monitor without D6 still goes black
        if mon:
            try:
                await ddc.power(mon, on)
            except Exception as e:
                log.info("monitor %s power: %s", mon, e)

    async def check(self, now=None):
        now = now or time.time()
        c, seats = self.cfg(), self.app["seats"]
        idle_min = float(c.get("off_after_min") or 0)
        night = in_window(c.get("night") or "", now)
        for sid in seats.kiosk_seats():
            st = seats.get(sid)
            if st["shows"] != "menu" or st.get("screen") == "off":
                continue
            last = self.touched.setdefault(sid, now)
            idle = (now - last) / 60
            if (idle_min and idle >= idle_min) or (night and idle >= 1):
                await self._set(sid, False)

    async def loop(self):
        while True:
            await asyncio.sleep(20)
            try:
                await self.check()
            except Exception as e:
                log.debug("power: %s", e)

