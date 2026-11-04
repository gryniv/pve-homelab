"""Time limits of systems: hours, minutes a day, warnings on the monitor, the end, and who is exempt."""

import time

import pytest

from pvehomelab import budget, demo

from conftest import login


def at(hour, minute=0):
    return time.mktime((2026, 11, 5, hour, minute, 0, 0, 0, -1))


@pytest.mark.parametrize("hours,now,left", [
    ("16:00-19:00", at(17, 30), 90), ("16:00-19:00", at(20), 0), ("", at(12), None),
    ("10:00-12:00, 16:00-19:00", at(11, 50), 10), ("22:00-01:00", at(23), 120),
])
def test_minutes_to_window_end(hours, now, left):
    assert budget.minutes_to_window_end(hours, now) == left


@pytest.fixture
def limits(client, monkeypatch):
    app = client.server.app
    monkeypatch.setitem(app["cfg"], "limits", {"100": {"hours": "00:00-23:59", "daily_min": 60, "grace_min": 5, "exempt": "ihor@pve"}})
    return app["limits"]


async def test_minutes_a_day(client, limits):
    assert limits.may_start(100, "guest@pve")
    limits._save({100: 59.7})
    assert not limits.may_start(100, "guest@pve")
    assert limits.may_start(100, "ihor@pve")                     # exempt
    assert limits.may_start(101, "guest@pve")                    # no limit on that one


async def test_starts_are_refused_outside_the_limit(client, limits):
    limits._save({100: 60})
    await login(client, "guest@pve")
    r = await client.post("/api/guests/qemu/100/start")
    assert r.status == 403 and "time" in (await r.json())["error"].lower()
    await login(client)                                          # exempt
    assert (await client.post("/api/guests/qemu/100/start")).status == 200


async def test_warnings_then_the_end(client, limits, monkeypatch):
    app = client.server.app
    asked, peeks = [], []
    monkeypatch.setattr(budget, "pvesh_create", lambda endpoint, **kw: asked.append(endpoint) or _done())

    async def peek(sid, vmid, seconds):
        peeks.append((sid, vmid))
    monkeypatch.setattr(app["launcher"], "peek_menu", peek)
    demo.WORLD[100]["status"] = "running"
    app["resources"].invalidate()
    app["seats"].set("igpu", shows=100)
    q = app["seats"].subscribe("igpu")
    limits._save({100: 51})
    limits.last_tick = time.time()
    await limits.tick()
    await _settle()
    notes = []
    while not q.empty():
        notes.append(q.get_nowait().get("notice"))
    assert {"limit": {"vmid": 100, "minutes": 9}} in notes and peeks == [("igpu", 100)]
    limits._save({100: 60})
    await limits.tick()
    assert asked == ["/nodes/demo/qemu/100/status/shutdown"]
    limits.ending[100] -= 6 * 60                                  # the grace minutes went by
    await limits.tick()
    assert asked[-1] == "/nodes/demo/qemu/100/status/stop"


async def _done():
    return None


async def _settle():
    import asyncio
    for _ in range(5):
        await asyncio.sleep(0)
