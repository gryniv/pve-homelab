"""What each screen on the host is showing: the menu, or a system on a GPU wired to its monitor.

The launcher says so when it switches a monitor; the page of that seat listens (/api/seat/events)
and, while its monitor shows a system, stands aside ("away"): no widgets, no effects, no keys acted
on, except both Ctrl keys, which bring the monitor back to the menu.
"""

import asyncio
import time


class Seats:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = {}
        self.listeners = {}   # seat id -> set of asyncio.Queue

    def kiosk_seats(self):
        """Seats drawn on this host's own GPUs (the "web" seat has none)."""
        return [sid for sid, s in self.cfg["seats"].items() if s.get("gpu")]

    def get(self, sid):
        return dict(self.state.get(sid) or {"shows": "menu", "input": "menu", "since": 0})

    def seat_of_monitor(self, ddc, mon):
        """The kiosk seat whose menu is on monitor `mon` (None if no menu is drawn there)."""
        return next((sid for sid in self.kiosk_seats() if ddc.monitor_for_gpu(self.cfg["seats"][sid]["gpu"]) == mon), None)

    def set(self, sid, shows=None, input=None):
        if not sid:
            return
        cur = self.get(sid)
        new = {"shows": cur["shows"] if shows is None else shows, "input": cur["input"] if input is None else input}
        if new["shows"] == "menu":
            new["input"] = "menu"     # the menu on screen has the keyboard, whatever held it
        if new == {k: cur[k] for k in ("shows", "input")}:
            return
        self.state[sid] = {**new, "since": time.time()}
        for q in list(self.listeners.get(sid, ())):
            q.put_nowait(self.get(sid))

    def subscribe(self, sid):
        q = asyncio.Queue()
        self.listeners.setdefault(sid, set()).add(q)
        return q

    def unsubscribe(self, sid, q):
        self.listeners.get(sid, set()).discard(q)
