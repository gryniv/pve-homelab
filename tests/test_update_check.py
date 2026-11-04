"""Settings → About → Check now: ask GitHub at once instead of waiting hours for the next check."""

import asyncio

from pvehomelab import update, util

from conftest import login


async def test_check_now_asks_again(client, monkeypatch):
    calls = []
    real = update.status

    async def counting(cfg):
        calls.append(1)
        return await real(cfg)
    monkeypatch.setattr(update, "status", counting)
    await login(client)
    assert (await client.get("/api/update")).status == 200
    first = len(calls)
    client.server.app["update"].value["checked"] -= 3600   # an answer from an hour ago
    r = await client.post("/api/update/check")
    assert r.status == 200, await r.text()
    d = await r.json()
    assert len(calls) == first + 1 and d["can_apply"] is True and d["enabled"] is True
    await client.post("/api/update/check")                   # again at once: the fresh answer stands
    assert len(calls) == first + 1


async def test_check_now_is_for_admins(client):
    assert (await client.post("/api/update/check")).status == 401
    await login(client, "guest@pve")
    assert (await client.post("/api/update/check")).status == 403


async def test_a_machine_up_for_less_than_the_ttl(monkeypatch):
    """monotonic() counts from boot: on a host rebooted 100 s ago (or a fresh CI runner) "never
    checked" must not look recent, or a 6-hour cache can't be asked again."""
    monkeypatch.setattr(util.time, "monotonic", lambda: 100.0)
    n = [0]

    async def fn():
        n[0] += 1
        return n[0]
    c = util.Cached(fn, 6 * 3600, stale=True)
    assert await c.get() == 1
    c.invalidate()
    assert await c.fresh() == 2


async def test_fresh_skips_a_stale_value():
    n = [0]

    async def fn():
        n[0] += 1
        return n[0]
    c = util.Cached(fn, 3600, stale=True)
    assert await c.get() == 1
    assert await c.get() == 1          # within the hour: the held value
    assert await c.fresh() == 2        # asked now
    await asyncio.sleep(0)
    assert await c.get() == 2


async def test_automatic_updates_switched_in_the_menu(client, tmp_path, monkeypatch):
    """Settings → About: the switch is kept beside config.yaml and wins over its update.auto."""
    from pvehomelab import config
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    assert update.settings({"update": {"auto": True}})["auto"] is True      # nothing from the menu yet
    assert (await client.put("/api/update/auto", json={"auto": True})).status == 401
    await login(client, "guest@pve")
    assert (await client.put("/api/update/auto", json={"auto": True})).status == 403
    await login(client)
    assert (await client.put("/api/update/auto", json={"auto": "yes"})).status == 400
    r = await client.put("/api/update/auto", json={"auto": True})
    assert r.status == 200 and (await r.json()) == {"auto": True}
    assert update.settings({})["auto"] is True
    assert (await (await client.get("/api/update")).json())["auto"] is True
    assert (await client.put("/api/update/auto", json={"auto": False})).status == 200
    assert update.settings({"update": {"auto": True}})["auto"] is False     # the menu wins
    assert (await (await client.get("/api/update")).json())["auto"] is False
    from pvehomelab import settings
    settings.change(resets=["update.auto"])                                 # back to config.yaml
    (tmp_path / update.MENU_FILE).write_text("junk", encoding="utf-8")     # the pre-0.8 file, broken
    assert update.settings({"update": {"auto": True}})["auto"] is True      # a broken file is ignored
