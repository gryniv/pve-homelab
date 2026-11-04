import pytest

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
    assert summarize_updates([]) == {"allowed": True, "count": 0, "proxmox": 0, "kernel": False, "checked": None,
                                     "packages": []}


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


async def test_backups_per_guest(client):
    await login(client)
    b = await (await client.get("/api/backups?days=7")).json()
    by = {g["vmid"]: g for g in b["guests"]}
    assert by[100]["count"] == 3 and not by[100]["stale"]
    assert by[102]["stale"] and by[102]["last"]          # 12 days old
    never = [v for v in demo.WORLD if v not in demo.BACKUP_AGE and not demo.WORLD[v].get("template")]
    assert never and all(by[v]["stale"] and by[v]["last"] == 0 for v in never)
    assert b["stale"] == len(never) + 1
    assert b["guests"][0]["last"] == 0  # never backed up comes first


async def test_backups_follow_guest_permissions(client):
    await login(client, "guest@pve")
    b = await (await client.get("/api/backups")).json()
    assert {g["vmid"] for g in b["guests"]} == demo.GUEST_SEES


async def test_backups_days_clamped(client):
    await login(client)
    assert (await (await client.get("/api/backups?days=9999")).json())["days"] == 365
    assert (await (await client.get("/api/backups?days=x")).json())["days"] == 7


def test_summarize_backups_dedupes_volumes():
    from pvehomelab.app import summarize_backups
    e = [{"volid": "a", "vmid": 100, "ctime": 10, "size": 1}, {"volid": "a", "vmid": 100, "ctime": 10, "size": 1}]
    b = summarize_backups(e, [{"vmid": 100, "name": "x", "type": "qemu"}], now=20, days=1)
    assert b["guests"][0]["count"] == 1 and not b["guests"][0]["stale"]


async def test_alerts_from_demo(client):
    await login(client)
    a = await (await client.get("/api/alerts")).json()
    # some demo guests were never backed up; Nextcloud's container is stopped, so its site is down
    assert [x["kind"] for x in a["alerts"]] == ["backup", "service"]
    assert {"kind": "service", "name": "Nextcloud", "guest": "nextcloud", "level": "warn"} in a["alerts"]
    # a guest serving a web UI goes down -> its service is reported
    assert (await client.post("/api/guests/lxc/201/shutdown")).status == 200
    a = await (await client.get("/api/alerts")).json()
    assert {"kind": "service", "name": "Jellyfin", "guest": "jellyfin", "level": "warn"} in a["alerts"]


async def test_alerts_respect_permissions(client):
    await login(client, "guest@pve")
    a = await (await client.get("/api/alerts")).json()
    assert not any(x["kind"] in ("disk", "pool", "storage") for x in a["alerts"])
    b = next((x for x in a["alerts"] if x["kind"] == "backup"), None)
    assert b is None or b["n"] <= len(demo.GUEST_SEES)


def test_build_alerts_thresholds_and_order():
    from pvehomelab.app import build_alerts
    limits = {"storage_pct": 90, "temp_c": 85, "backup_days": 7}
    a = build_alerts(limits, host={"temp": 99},
                     storages=[{"id": "local", "used": 91, "total": 100}, {"id": "ok", "used": 10, "total": 100},
                               {"id": "full", "used": 99, "total": 100}],
                     disks={"disks": [{"ok": False, "health": "FAILED", "model": "X", "dev": "/dev/sda"},
                                      {"ok": False, "health": "UNKNOWN", "model": "Y", "dev": "/dev/sdb"}],
                            "pools": [{"ok": False, "name": "tank", "health": "DEGRADED"}]},
                     backups={"stale": 2, "days": 7, "guests": [{"stale": True, "last": 0}, {"stale": True, "last": 5}]},
                     services=[{"name": "Jellyfin", "status": "stopped"}, {"name": "Up", "status": "running"}])
    kinds = [(x["kind"], x["level"]) for x in a]
    assert ("disk", "bad") in kinds and ("pool", "bad") in kinds and ("temp", "bad") in kinds
    assert ("storage", "warn") in kinds and ("storage", "bad") in kinds
    assert not any(x["kind"] == "storage" and x["name"] == "ok" for x in a)
    assert sum(x["kind"] == "disk" for x in a) == 1          # unknown SMART is not an alert
    assert next(x for x in a if x["kind"] == "backup")["never"] == 1
    assert [x["level"] for x in a] == sorted([x["level"] for x in a], key=lambda l: l != "bad")


def test_build_alerts_quiet_when_all_fine():
    from pvehomelab.app import build_alerts
    assert build_alerts({"storage_pct": 90, "temp_c": 85, "backup_days": 7}, host={"temp": 50}) == []


async def test_wol_list_and_wake(client):
    await login(client)
    d = await (await client.get("/api/wol")).json()
    assert d["allowed"] and [x["name"] for x in d["targets"]] == ["NAS", "Desktop PC"]
    assert "mac" not in d["targets"][0]           # the menu needs only names
    demo.WOKEN.clear()
    r = await client.post(f"/api/wol/{d['targets'][1]['id']}")
    assert r.status == 200 and demo.WOKEN == ["Desktop PC"]
    assert (await client.post("/api/wol/99")).status == 404
    assert (await client.post("/api/wol/x")).status == 404


async def test_wol_needs_power_rights(client):
    await login(client, "guest@pve")
    assert (await (await client.get("/api/wol")).json()) == {"allowed": False, "targets": []}
    assert (await client.post("/api/wol/0")).status == 403


async def test_health_reports_running_code(client):
    r = await client.get("/api/health")
    assert r.status == 200
    d = await r.json()
    assert d["ok"] and set(d) == {"ok", "version", "commit"}


async def test_console_type_checked(client):
    await login(client)
    assert (await client.post("/api/console/201?type=docker")).status == 400


async def test_console_asks_proxmox_for_the_right_guest_type(client, monkeypatch):
    await login(client)
    asked = []
    pve = client.server.app["pve"]

    async def post(t, endpoint, **data):
        asked.append(endpoint)
        return {"port": 5901, "ticket": "PVEVNC:x"}
    monkeypatch.setattr(pve, "post", post)
    r = await client.post("/api/console/201?type=lxc")
    assert r.status == 200 and asked[-1].endswith("/lxc/201/vncproxy")
    tok = (await r.json())["token"]
    assert client.server.app["consoles"][tok]["type"] == "lxc"
    await client.post("/api/console/100")
    assert asked[-1].endswith("/qemu/100/vncproxy")


async def test_guest_history(client):
    await login(client)
    running = next(v for v, g in demo.WORLD.items() if g["status"] == "running")
    typ = demo.WORLD[running]["type"]
    d = await (await client.get(f"/api/guests/{typ}/{running}/rrd?timeframe=day")).json()
    assert d["timeframe"] == "day" and len(d["time"]) == 70 == len(d["cpu"]) == len(d["netin"])
    assert d["time"] == sorted(d["time"]) and all(0 <= c <= 100 for c in d["cpu"])
    assert d["maxmem"] > 0


async def test_guest_history_gaps_while_off(client):
    await login(client)
    stopped = next(v for v, g in demo.WORLD.items() if g["status"] == "stopped")
    d = await (await client.get(f"/api/guests/{demo.WORLD[stopped]['type']}/{stopped}/rrd")).json()
    assert d["cpu"][-1] is None and d["cpu"][0] is not None   # off now, on an hour ago


async def test_guest_history_checks_input_and_rights(client):
    await login(client)
    assert (await client.get("/api/guests/docker/100/rrd")).status == 400
    assert (await client.get("/api/guests/qemu/100/rrd?timeframe=year")).status == 400
    await client.post("/api/logout")
    await login(client, "guest@pve")
    hidden = next(v for v in demo.WORLD if v not in demo.GUEST_SEES)
    assert (await client.get(f"/api/guests/{demo.WORLD[hidden]['type']}/{hidden}/rrd")).status == 403


def test_summarize_rrd_orders_and_keeps_gaps():
    from pvehomelab.app import summarize_rrd
    d = summarize_rrd([{"time": 20, "cpu": 0.5, "maxmem": 8}, {"time": 10}, {"cpu": 1}])
    assert d["time"] == [10, 20] and d["cpu"] == [None, 50.0] and d["maxmem"] == 8


async def test_guest_info_snapshots_and_backup(client):
    await login(client)
    d = await (await client.get("/api/guests/qemu/100/info")).json()
    assert [s["name"] for s in d["snapshots"]] == ["before-upgrade", "clean-install"]   # newest first, no "current"
    assert d["snapshots"][0]["ram"] is True and d["snapshots"][1]["ram"] is False
    assert d["backup"]["count"] == 3 and d["backup"]["last"] > 0


async def test_guest_info_without_backup_or_snapshots(client):
    await login(client)
    never = next(v for v in demo.WORLD if v not in demo.BACKUP_AGE and v not in demo.SNAPSHOTS)
    d = await (await client.get(f"/api/guests/{demo.WORLD[never]['type']}/{never}/info")).json()
    assert d["snapshots"] == [] and d["backup"] == {"last": 0, "count": 0, "size": 0}


async def test_guest_info_hidden_guest_is_404(client):
    await login(client, "guest@pve")
    hidden = next(v for v in demo.WORLD if v not in demo.GUEST_SEES)
    assert (await client.get(f"/api/guests/{demo.WORLD[hidden]['type']}/{hidden}/info")).status == 404


# ---------- each person sees their own: services, GPUs, launch jobs ----------
async def test_services_of_guests_you_cannot_see_are_not_listed(client):
    await login(client, "guest@pve")
    svcs = await (await client.get("/api/services")).json()
    vmids = {s["guest"]["vmid"] for s in svcs if s["guest"] and s["guest"]["type"] != "node"}
    assert vmids <= demo.GUEST_SEES
    assert not any(s["name"] == "Nextcloud" for s in svcs)     # CT 203, stopped and not theirs
    assert any(s["guest"] is None for s in svcs)               # links stay
    await login(client)
    assert any(s["name"] == "Nextcloud" for s in await (await client.get("/api/services")).json())


async def test_gpus_do_not_name_vms_you_cannot_see(client):
    demo.WORLD[102]["status"] = "running"
    client.server.app["resources"].invalidate()
    await login(client, "guest@pve")
    rtx = next(g for g in await (await client.get("/api/gpus")).json() if g["pci"] == "0000:01:00.0")
    assert rtx["running_vm"] == 0 and 102 not in rtx["assigned_vms"]
    await login(client)
    rtx = next(g for g in await (await client.get("/api/gpus")).json() if g["pci"] == "0000:01:00.0")
    assert rtx["running_vm"] == 102


async def test_a_launch_job_is_its_starters(client):
    await login(client)
    systems = await (await client.get("/api/systems", headers={"X-Seat": "igpu"})).json()
    vm = next(s for s in systems if s["vmid"] == 100)
    gpu = next(o["pci"] for o in vm["options"] if o["mode"] == "passthrough")
    r = await client.post("/api/launch", json={"vmid": 100, "gpu": gpu}, headers={"X-Seat": "igpu"})
    jid = (await r.json())["id"]
    assert (await client.get(f"/api/jobs/{jid}")).status == 200
    await login(client, "guest@pve")
    assert (await client.get(f"/api/jobs/{jid}")).status == 404


# ---------- a guest's resources and options ----------
async def test_guest_settings_read_and_written_with_your_rights(client):
    await login(client)
    c = await (await client.get("/api/guests/lxc/201/config")).json()
    assert c["memory"] == 4096 and c["cores"] == 4 and c["onboot"] is False and c["can"]["memory"] is True
    r = await client.put("/api/guests/lxc/201/config", json={"memory": 6144, "cores": 6, "swap": 512, "onboot": True,
                                                            "startup": {"order": 2, "up": 30}, "tags": ["media", "gpu"],
                                                            "description": "Jellyfin"})
    assert r.status == 200, await r.text()
    c = await r.json()
    assert (c["memory"], c["cores"], c["swap"], c["onboot"]) == (6144, 6, 512, True)
    assert c["startup"] == {"order": 2, "up": 30} and c["tags"] == ["media", "gpu"] and c["description"] == "Jellyfin"
    c = await (await client.put("/api/guests/lxc/201/config", json={"startup": {}, "tags": [], "description": ""})).json()
    assert c["startup"] == {} and c["tags"] == [] and c["description"] == ""


async def test_a_running_vm_keeps_new_memory_for_its_next_start(client):
    await login(client)
    demo.WORLD[101]["status"] = "running"
    c = await (await client.put("/api/guests/qemu/101/config", json={"memory": 12288})).json()
    assert c["memory"] == 8192 and c["pending"] == ["memory"]
    assert (await client.post("/api/guests/qemu/101/shutdown")).status == 200
    c = await (await client.get("/api/guests/qemu/101/config")).json()
    assert c["memory"] == 12288 and c["pending"] == []


@pytest.mark.parametrize("body", [{"memory": 4}, {"cores": 0}, {"onboot": "yes"}, {"tags": ["Bad Tag"]},
                                  {"startup": {"order": -1}}, {"memory": True}, {}, [1], {"balloon": 9000, "memory": 2048}])
async def test_guest_settings_refuse_odd_values(client, body):
    await login(client)
    assert (await client.put("/api/guests/qemu/101/config", json=body)).status == 400


async def test_guest_settings_need_the_privileges(client):
    await login(client, "guest@pve")
    c = await (await client.get("/api/guests/lxc/201/config")).json()
    assert c["can"] == {"memory": False, "cpu": False, "options": False}
    assert (await client.put("/api/guests/lxc/201/config", json={"memory": 8192})).status == 403
    assert (await client.get("/api/guests/lxc/203/config")).status == 403      # not theirs to see
