"""Proxmox updates in the top bar: when the lists were last checked, checking again, and who may."""

import asyncio
import time

from pvehomelab import app as A, demo, prefs

from conftest import login


def test_last_check_is_the_newest_good_apt_update():
    tasks = [{"type": "aptupdate", "status": "OK", "starttime": 100, "endtime": 120},
             {"type": "aptupdate", "status": "command 'apt-get update' failed: exit code 100", "endtime": 900},
             {"type": "vzdump", "status": "OK", "endtime": 950},
             {"type": "aptupdate", "status": "OK", "starttime": 500}]   # no endtime: the start is enough
    assert A.last_apt_check(tasks) == 500
    assert A.last_apt_check([]) is None and A.last_apt_check(None) is None
    assert A.last_apt_check([{"type": "aptupdate", "status": "OK"}]) is None


async def test_the_answer_says_when_the_lists_were_checked(client):
    await login(client)
    u = await (await client.get("/api/node-updates")).json()
    assert u["checked"] == int(demo.APT_CHECKED)


async def test_without_the_task_list_the_packages_still_come(client, monkeypatch):
    await login(client)
    pve = client.server.app["pve"]
    real = pve.get

    async def no_tasks(t, endpoint, **params):
        if endpoint.endswith("/tasks"):
            raise A.PVEError(403, "no Sys.Audit")
        return await real(t, endpoint, **params)
    monkeypatch.setattr(pve, "get", no_tasks)
    u = await (await client.get("/api/node-updates")).json()
    assert u["count"] == len(demo.APT_UPDATES) and u["checked"] is None


async def test_check_now(client):
    await login(client)
    before = time.time()
    r = await client.post("/api/node-updates/refresh")
    assert r.status == 200, await r.text()
    u = await r.json()
    assert u["allowed"] and u["count"] == len(demo.APT_UPDATES)
    assert u["checked"] >= before   # the run just made


async def test_check_now_needs_sys_modify(client):
    assert (await client.post("/api/node-updates/refresh")).status == 401
    await login(client, "guest@pve")
    assert (await client.post("/api/node-updates/refresh")).status == 403


async def test_a_failed_check_says_why(client):
    await login(client)
    demo.STATE["fail"] = "apt"
    r = await client.post("/api/node-updates/refresh", headers={"X-Lang": "en"})
    assert r.status == 502
    msg = (await r.json())["error"]
    assert msg.startswith("Could not check for updates") and "exit code 100" in msg


async def test_two_at_once_share_one_run(client, monkeypatch):
    await login(client)
    pve = client.server.app["pve"]
    runs, real = [], pve.post

    async def counted(t, endpoint, **data):
        if endpoint.endswith("/apt/update"):
            runs.append(endpoint)
        return await real(t, endpoint, **data)
    monkeypatch.setattr(pve, "post", counted)
    a, b = await asyncio.gather(client.post("/api/node-updates/refresh"), client.post("/api/node-updates/refresh"))
    assert (a.status, b.status) == (200, 200) and len(runs) == 1


def test_the_top_bar_setting_keeps_its_type():
    assert prefs._merge(prefs.DEFAULT, {"top": {"pve_updates": False}})["top"] == {"pve_updates": False}
    assert prefs._merge(prefs.DEFAULT, {"top": {"pve_updates": "no"}})["top"] == {"pve_updates": True}
    assert prefs._merge(prefs.DEFAULT, {"top": "off"})["top"] == {"pve_updates": True}
