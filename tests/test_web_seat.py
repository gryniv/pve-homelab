"""The menu in a browser elsewhere, through a reverse proxy (web.allow_from): who gets in, which
seat they are, and that nothing they do switches a monitor or hands over a GPU."""

import asyncio
import logging

import pytest

from pvehomelab import app as A, launch as L
from pvehomelab.ddc import DDC

from conftest import login

PROXY = "192.168.8.150"
SITE = {"Host": "home.example.com", "X-Forwarded-For": "203.0.113.7"}


@pytest.fixture
def via(monkeypatch, client):
    """Requests come from this address (the test client itself is always loopback)."""
    def set_peer(addr, allow=(PROXY,), enabled=True):
        monkeypatch.setattr(A, "peer", lambda req: addr)
        monkeypatch.setitem(client.server.app["cfg"], "web", {"enabled": enabled, "allow_from": list(allow)})
    return set_peer


async def test_others_beyond_loopback_are_refused(client, via):
    via("192.168.8.99")
    assert (await client.get("/api/public", headers=SITE)).status == 403
    via(PROXY, enabled=False)   # web access turned off: the proxy too
    assert (await client.get("/api/public", headers=SITE)).status == 403
    via("192.168.8.99", allow=["192.168.8.0/24"])   # a network is fine as well
    assert (await client.get("/api/public", headers=SITE)).status == 200


async def test_the_proxy_gets_in_as_the_web_seat(client, via):
    via(PROXY)
    pub = await (await client.get("/api/public?seat=igpu", headers={**SITE, "X-Seat": "igpu"})).json()
    assert pub["seat"]["id"] == "web" and pub["seat"]["remote"] is True and pub["seat"]["gpu_name"] == ""


async def test_through_the_proxy_its_site_name_is_trusted_but_not_a_foreign_origin(client, via):
    via(PROXY)
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"},
                          headers={**SITE, "Origin": "https://evil.example"})
    assert r.status == 403
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"},
                          headers={**SITE, "Origin": "https://home.example.com"})
    assert r.status == 200, await r.text()


async def test_on_the_host_an_unknown_name_is_still_refused(client, via):
    via("127.0.0.1")
    assert (await client.get("/api/public", headers={"Host": "home.example.com", "X-Seat": "igpu"})).status == 421


async def test_no_seat_asked_on_the_host_is_the_first_seat(client):
    pub = await (await client.get("/api/public")).json()
    assert pub["seat"]["id"] == "igpu"


async def test_the_login_names_the_person_behind_the_proxy(client, via, caplog):
    via(PROXY)
    with caplog.at_level(logging.INFO, logger="pvehomelab"):
        r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers=SITE)
    assert r.status == 200
    assert any("on seat web from 203.0.113.7" in m for m in caplog.messages), caplog.messages


async def test_the_session_cookie_is_secure_behind_https(client, via):
    via(PROXY)
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers={**SITE, "X-Forwarded-Proto": "https"})
    assert "Secure" in r.headers["Set-Cookie"]
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers=SITE)   # a plain-HTTP proxy
    assert "Secure" not in r.headers["Set-Cookie"]
    via("127.0.0.1")   # the kiosk on the host: plain HTTP, and a forged header changes nothing
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" not in r.headers["Set-Cookie"]


async def test_from_a_browser_a_system_opens_here_or_on_its_own_gpu(client, via):
    via(PROXY)
    await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers=SITE)
    systems = {s["vmid"]: s for s in await (await client.get("/api/systems", headers=SITE)).json()}
    assert [o["mode"] for o in systems[100]["options"]] == ["console"]                # no GPU of its own
    assert [o["mode"] for o in systems[102]["options"]] == ["console", "remote"]      # its RTX 4070
    assert not any(o["mode"] in ("virgl", "passthrough") for s in systems.values() for o in s["options"])


async def test_a_start_from_a_browser_switches_nothing(client, via, monkeypatch):
    touched = []

    async def no(*a, **k):
        touched.append(a)
    monkeypatch.setattr(DDC, "switch_to_gpu", no)
    monkeypatch.setattr(L.Launcher, "_assign_gpu", no)
    via(PROXY)
    await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers=SITE)
    r = await client.post("/api/launch", json={"vmid": 100, "gpu": "console"}, headers=SITE)
    assert r.status == 200, await r.text()
    job = (await r.json())["id"]
    for _ in range(40):
        j = await (await client.get(f"/api/jobs/{job}", headers=SITE)).json()
        if j["done"]:
            break
        await asyncio.sleep(0.2)
    assert j["done"] and not j.get("error") and j["result"] == {"console": 100}, j
    assert touched == []
    # a GPU that is not the system's own is not on offer from here
    r = await client.post("/api/launch", json={"vmid": 102, "gpu": "0000:00:02.0"}, headers=SITE)
    assert r.status == 400


async def test_only_real_gpus_are_offered_from_a_browser(monkeypatch):
    """A VM may hold more PCI devices than its GPU (the GPU's audio, a USB controller): those are not
    something to start it on. Seen on a host: 0000:79:00.6 offered as "its own GPU"."""
    async def gpus(running):
        return [{"pci": "0000:02:00.0", "name": "RTX 5070 Ti", "vendor": "nvidia", "integrated": False, "running_vm": None}]

    async def running(fresh=False):
        return set()
    monkeypatch.setattr(L.G, "list_gpus", gpus)
    launcher = L.Launcher({"cfg": {"seats": {}}, "running": running})
    opts = await launcher._remote_options({"vmid": 102, "vga": "std", "gpus": ["0000:02:00.0", "0000:79:00.6"]})
    assert [(o["mode"], o["pci"]) for o in opts] == [("console", "console"), ("remote", "0000:02:00.0")]


# ---------- what a browser elsewhere learns before signing in (web.sign_in) ----------
async def test_sign_in_screen_elsewhere_is_minimal_by_default(client, via):
    via(PROXY)
    pub = await (await client.get("/api/public", headers=SITE)).json()
    assert pub["users"] == [] and pub["host"] is None and pub["guests"] is None
    assert pub["stats"] is False and pub["version"] == "" and pub["ip"] == "" and pub["node"]
    assert (await client.get("/api/host", headers=SITE)).status == 401


async def test_sign_in_levels(client, via, monkeypatch):
    via(PROXY)
    web_cfg = client.server.app["cfg"]["web"]
    monkeypatch.setitem(web_cfg, "sign_in", "users")
    pub = await (await client.get("/api/public", headers=SITE)).json()
    assert pub["users"] and pub["host"] is None and pub["stats"] is False
    monkeypatch.setitem(web_cfg, "sign_in", "full")
    pub = await (await client.get("/api/public", headers=SITE)).json()
    assert pub["users"] and pub["host"] and pub["guests"] and pub["stats"] is True
    assert (await client.get("/api/host", headers=SITE)).status == 200
    monkeypatch.setitem(web_cfg, "sign_in", "everything")      # unknown: the safe one
    assert (await (await client.get("/api/public", headers=SITE)).json())["users"] == []


async def test_signed_in_elsewhere_sees_their_own_figures(client, via):
    via(PROXY)
    await client.post("/api/login", json={"user": "guest@pve", "password": "x"}, headers=SITE)
    pub = await (await client.get("/api/public", headers=SITE)).json()
    assert pub["stats"] is True and pub["users"]
    assert pub["guests"]["running"] + pub["guests"]["stopped"] == 3     # the three guest@pve may see
    assert (await client.get("/api/host", headers=SITE)).status == 200


async def test_the_screen_on_the_host_shows_everything(client):
    pub = await (await client.get("/api/public", headers={"X-Seat": "igpu"})).json()
    assert pub["users"] and pub["host"] and pub["stats"] is True and pub["version"]
    assert (await client.get("/api/host")).status == 200


async def test_weather_for_a_stranger_is_the_configured_city(client, via):
    via(PROXY)
    city = client.server.app["cfg"]["weather"]["city"]
    w = await (await client.get("/api/weather?city=Lisbon", headers=SITE)).json()
    assert w["city"] == city
    await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers=SITE)
    w = await (await client.get("/api/weather?city=Lisbon", headers=SITE)).json()
    assert w["city"] == "Lisbon"
