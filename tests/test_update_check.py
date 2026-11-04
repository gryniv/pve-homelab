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
