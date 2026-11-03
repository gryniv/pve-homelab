"""The HTTP API through the demo: sessions, permissions, guests, services."""

from pvehomelab import demo

from conftest import login

SEAT = {"X-Seat": "igpu"}


async def test_public_lists_users_without_login(client):
    r = await client.get("/api/public", headers=SEAT)
    assert r.status == 200
    assert {u["id"] for u in (await r.json())["users"]} >= {"ihor@pve", "guest@pve"}


async def test_data_needs_a_session(client):
    for path in ("/api/guests", "/api/services", "/api/systems", "/api/me"):
        assert (await client.get(path, headers=SEAT)).status == 401, path


async def test_logout_ends_the_session(client):
    await login(client)
    assert (await client.get("/api/me")).status == 200
    await client.post("/api/logout")
    assert (await client.get("/api/me")).status == 401


async def test_guest_sees_only_what_pve_allows(client):
    await login(client, "guest@pve")
    vmids = {g["vmid"] for g in await (await client.get("/api/guests")).json()}
    assert vmids == demo.GUEST_SEES


async def test_guest_cannot_power_others(client):
    await login(client, "guest@pve")
    other = next(v for v in demo.WORLD if v not in demo.GUEST_SEES)
    typ = demo.WORLD[other]["type"]
    r = await client.post(f"/api/guests/{typ}/{other}/start")
    assert r.status == 403


async def test_guest_cannot_read_error_journal(client):
    await login(client, "guest@pve")
    assert (await client.get("/api/logs")).status == 403


async def test_start_and_shutdown_a_guest(client):
    await login(client)
    vmid = next(v for v, g in demo.WORLD.items() if g["status"] == "stopped")
    typ = demo.WORLD[vmid]["type"]
    assert (await client.post(f"/api/guests/{typ}/{vmid}/start")).status == 200
    assert demo.WORLD[vmid]["status"] == "running"
    assert (await client.post(f"/api/guests/{typ}/{vmid}/shutdown")).status == 200
    assert demo.WORLD[vmid]["status"] == "stopped"


async def test_unknown_guest_action_refused(client):
    await login(client)
    vmid = next(iter(demo.WORLD))
    r = await client.post(f"/api/guests/{demo.WORLD[vmid]['type']}/{vmid}/destroy")
    assert 400 <= r.status < 500


async def test_services_are_listed(client):
    await login(client)
    services = await (await client.get("/api/services")).json()
    assert services and all({"key", "name", "url"} <= s.keys() for s in services)


async def test_prefs_round_trip(client):
    await login(client)
    r = await client.put("/api/prefs", json={"skin": "forest", "avatar": 2})
    assert (await r.json())["skin"] == "forest"
    me = await (await client.get("/api/me")).json()
    assert me["prefs"]["skin"] == "forest" and me["prefs"]["avatar"] == 2


async def test_bad_ids_are_400_not_500(client):
    await login(client)
    assert (await client.post("/api/guests/qemu/abc/start")).status == 400
    assert (await client.post("/api/launch", json={"vmid": "x", "gpu": "0000:01:00.0"}, headers=SEAT)).status == 400
    assert (await client.post("/api/launch", json={"vmid": 100}, headers=SEAT)).status == 400
    assert (await client.post("/api/console/abc")).status == 400
    assert (await client.get("/api/jobs/abc")).status == 404


async def test_node_updates_summary(client):
    await login(client)
    u = await (await client.get("/api/node-updates")).json()
    assert u["allowed"] and u["count"] == len(demo.APT_UPDATES)
    assert u["proxmox"] == 3 and u["kernel"] is True
    assert u["packages"][0]["origin"] == "Proxmox"  # Proxmox packages first


async def test_node_updates_need_sys_modify(client):
    await login(client, "guest@pve")
    assert await (await client.get("/api/node-updates")).json() == {"allowed": False}


def test_summarize_updates_empty():
    from pvehomelab.app import summarize_updates
    assert summarize_updates([]) == {"allowed": True, "count": 0, "proxmox": 0, "kernel": False, "packages": []}


async def test_disks_summary(client):
    await login(client)
    d = await (await client.get("/api/disks")).json()
    assert d["allowed"] and d["problems"] == 0
    assert len(d["disks"]) == len(demo.DISKS) and d["pools"][0]["name"] == "nvme2tb"
    assert next(x for x in d["disks"] if x["dev"] == "/dev/sda")["wearout"] is None  # "N/A" for spinning disks


async def test_disks_need_sys_audit(client):
    await login(client, "guest@pve")
    assert await (await client.get("/api/disks")).json() == {"allowed": False}


def test_summarize_disks_problems_first():
    from pvehomelab.app import summarize_disks
    d = summarize_disks([{"devpath": "/dev/a", "health": "PASSED"}, {"devpath": "/dev/b", "health": "FAILED"},
                         {"devpath": "/dev/c"}], [{"name": "tank", "health": "DEGRADED"}])
    assert [x["dev"] for x in d["disks"]] == ["/dev/b", "/dev/c", "/dev/a"]
    assert d["problems"] == 2  # failed disk + degraded pool; unknown SMART is not counted
