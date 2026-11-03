"""Pure logic: no host, no network."""

import asyncio

import pytest
import yaml

from pvehomelab import caddy, config, discover, errlog, gpus, setup, update, util


# ---------- discover ----------
@pytest.mark.parametrize("title,guest,port,name,icon", [
    ("Jellyfin", "media", 8096, "Jellyfin", "jellyfin"),
    ("", "home-assistant", 8123, "Home Assistant", "home-assistant"),
    ("", "box", 32400, "Plex", "plex"),          # only the port says what it is
    ("My Wiki | intranet", "wiki-ct", 3000, "My Wiki", "wiki-ct"),
    ("", "", 1234, "port 1234", ""),
])
def test_identify(title, guest, port, name, icon):
    assert discover.identify(title, guest, port) == (name, icon)


def test_title_beats_guest_name():
    assert discover.identify("Grafana", "jellyfin", 3000)[0] == "Grafana"


def test_parse_proc_net():
    text = (
        "  sl  local_address rem_address   st tx_queue rx_queue\n"
        "   0: 00000000:1F90 00000000:0000 0A 00000000:00000000\n"   # 0.0.0.0:8080 listen
        "   1: 0100007F:0CEA 00000000:0000 0A 00000000:00000000\n"   # 127.0.0.1:3306 listen: loopback, skipped
        "   2: 0A00000A:0050 0A000001:C350 01 00000000:00000000\n"   # established, skipped
    )
    assert discover.parse_proc_net(text) == {8080}


def test_notes_links():
    desc = "See [Grafana](http://10.0.0.5:3000) and https://wiki.home.example/start. Again http://10.0.0.5:3000"
    assert discover._notes_links(desc) == [("Grafana", "http://10.0.0.5:3000"), ("", "https://wiki.home.example/start")]


def test_merge_prefers_caddy():
    caddy_list = [{"key": "jf", "name": "Jellyfin", "url": "https://jf.home", "upstream": "10.0.0.2:8096",
                   "guest": {"type": "lxc", "vmid": 201, "name": "jellyfin"}}]
    found = [
        {"key": "ct201-8096", "name": "Jellyfin", "url": "http://10.0.0.2:8096", "port": 8096, "source": "port",
         "guest": {"type": "lxc", "vmid": 201, "name": "jellyfin"}},
        {"key": "ct202-2283", "name": "Immich", "url": "http://10.0.0.3:2283", "port": 2283, "source": "port",
         "guest": {"type": "lxc", "vmid": 202, "name": "immich"}},
    ]
    out = discover.merge(caddy_list, found)
    assert [s["key"] for s in out] == ["jf", "ct202-2283"]
    assert out[0]["source"] == "caddy"


# ---------- caddy ----------
def test_caddy_walk_nested():
    handlers = [{"handler": "subroute", "routes": [{"handle": [
        {"handler": "reverse_proxy", "upstreams": [{"dial": "10.0.0.2:8096"}]}]}]}]
    acc = []
    caddy._walk(handlers, acc)
    assert acc == ["10.0.0.2:8096"]


def test_caddy_build():
    cfg = {"services": {"jf": {"name": "Jellyfin TV"}}, "links": [{"name": "Router", "url": "http://192.168.1.1/"}]}
    rts = [{"key": "jf", "host": "jf.home.example", "upstream": "10.0.0.2:8096"},
           {"key": "pve", "host": "pve.home.example", "upstream": "10.0.0.1:8006"}]
    ips = {"10.0.0.2": ("lxc", 201, "jellyfin")}
    out = {s["key"]: s for s in caddy.build(cfg, rts, ips, "10.0.0.1")}
    assert out["jf"]["name"] == "Jellyfin TV" and out["jf"]["icon"] == "jellyfin"
    assert out["jf"]["guest"] == {"type": "lxc", "vmid": 201, "name": "jellyfin"}
    assert out["pve"]["guest"]["type"] == "node"
    assert out["link0"]["host"] == "192.168.1.1" and out["link0"]["guest"] is None


# ---------- gpus ----------
def _edid(name=b"DELL P2418D", serial=b"ABC123"):
    raw = bytearray(128)
    raw[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    raw[8], raw[9] = 0x10, 0xAC  # "DEL"
    for off, tag, txt in ((54, 0xFC, name), (72, 0xFF, serial)):
        raw[off:off + 5] = bytes([0, 0, 0, tag, 0])
        raw[off + 5:off + 18] = (txt + b"\n").ljust(13, b" ")
    return bytes(raw)


def test_parse_edid():
    assert gpus.parse_edid(_edid()) == {"vendor": "DEL", "name": "DELL P2418D", "serial": "ABC123"}


def test_parse_edid_rejects_garbage():
    assert gpus.parse_edid(b"\0" * 128) is None
    assert gpus.parse_edid(b"short") is None


@pytest.mark.parametrize("addr,want", [("0000:01:00", "0000:01:00.0"), ("0000:01:00.1", "0000:01:00.1"),
                                       ("0000:0A:00", "0000:0a:00.0")])
def test_gpu_of(addr, want):
    assert gpus.gpu_of(addr) == want


# ---------- setup ----------
CAPS = """Model: P2418D
   Feature: 10 (Brightness)
   Feature: 60 (Input Source)
      Values:
         0f: DisplayPort-1
         11: HDMI-1
         12: HDMI-2
   Feature: 62 (Audio speaker volume)
"""


def test_parse_inputs():
    assert setup.parse_inputs(CAPS) == {0x0F: "DisplayPort-1", 0x11: "HDMI-1", 0x12: "HDMI-2"}
    assert setup.parse_inputs("no such feature") == {}


@pytest.mark.parametrize("conn,want", [("HDMI-A-1", 0x11), ("HDMI-A-2", 0x12), ("DP-1", 0x0F), ("DP-3", None),
                                       (None, None), ("eDP-1", None)])
def test_guess_input(conn, want):
    assert setup.guess_input(conn, setup.parse_inputs(CAPS)) == want


def test_render_is_valid_yaml():
    seats = [{"integrated": True, "name": "UHD 770", "pci": "0000:00:02.0",
              "connectors": [{"name": "HDMI-A-1", "connected": True}]}]
    monitors = [{"bus": 4, "connector": "HDMI-A-1", "pci": "0000:00:02.0", "model": "P2418D",
                 "inputs": setup.parse_inputs(CAPS)}]
    cfg = yaml.safe_load(setup.render(seats, monitors, 200, "Lviv", "en"))
    assert cfg["seats"]["igpu"]["gpu"] == "0000:00:02.0"
    assert cfg["monitors"]["mon0"]["ddc_bus"] == 4
    assert cfg["weather"]["city"] == "Lviv"
    assert cfg["listen"] == "127.0.0.1:8900"


# ---------- update ----------
@pytest.mark.parametrize("repo,slug", [("https://github.com/gryniv/pve-homelab.git", "gryniv/pve-homelab"),
                                       ("git@github.com:gryniv/pve-homelab", "gryniv/pve-homelab"),
                                       ("gryniv/pve-homelab", "gryniv/pve-homelab"), ("", ""), ("not a repo", "")])
def test_repo_slug(repo, slug):
    assert update._repo_slug(repo) == slug


def test_ver_order():
    assert update._ver("v0.10.0") > update._ver("0.9.9") > update._ver("0.4") > update._ver(None)


# ---------- config ----------
def test_config_merge_deep():
    out = config._merge(config.DEFAULTS, {"launch": {"allow_igpu": True}, "weather": {"city": "Lviv"}})
    assert out["launch"] == {**config.DEFAULTS["launch"], "allow_igpu": True}
    assert out["weather"]["units"] == config.DEFAULTS["weather"]["units"]
    assert config.DEFAULTS["launch"]["allow_igpu"] is False  # defaults untouched


# ---------- errlog ----------
def test_errlog_dedupes():
    errlog.RING.clear()
    a = errlog.add("error", "js", "boom", seat="igpu")
    b = errlog.add("error", "js", "boom", seat="igpu")
    c = errlog.add("error", "js", "boom", seat="gpu0")
    assert a is b and a["count"] == 2 and c is not a


def test_errlog_caps_sizes():
    errlog.RING.clear()
    e = errlog.add("error", "js", "m" * 1000, detail="d" * 10000)
    assert len(e["msg"]) == 500 and len(e["detail"]) == 4000


# ---------- util.Cached ----------
async def test_cached_keeps_old_value_on_failure():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("down")
        return "v1"

    c = util.Cached(fn, ttl=0)
    assert await c.get() == "v1"
    assert await c.get() == "v1"  # refresh failed: the old value stays
    assert calls["n"] == 2


async def test_cached_first_failure_raises():
    async def fn():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        await util.Cached(fn, ttl=60).get()


async def test_cached_stale_returns_at_once():
    gate = asyncio.Event()
    n = {"v": 0}

    async def fn():
        n["v"] += 1
        if n["v"] > 1:
            await gate.wait()
        return n["v"]

    c = util.Cached(fn, ttl=0, stale=True)
    assert await c.get() == 1
    assert await c.get() == 1  # expired: old value now, refresh in the background
    gate.set()
    await asyncio.sleep(0)


# ---------- wol ----------
from pvehomelab import wol  # noqa: E402


@pytest.mark.parametrize("mac", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabbccddeeff"])
def test_wol_parse_mac(mac):
    assert wol.parse_mac(mac) == bytes.fromhex("aabbccddeeff")


@pytest.mark.parametrize("mac", ["", "aa:bb:cc:dd:ee", "aa:bb-cc:dd:ee:ff", "zz:bb:cc:dd:ee:ff", None])
def test_wol_bad_mac(mac):
    with pytest.raises(ValueError):
        wol.parse_mac(mac)


def test_wol_magic_packet():
    p = wol.magic_packet("01:02:03:04:05:06")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes([1, 2, 3, 4, 5, 6]) and p[-6:] == p[6:12]


def test_wol_targets_skip_bad_entries():
    cfg = {"wol": [{"name": "A", "mac": "aa:bb:cc:dd:ee:01"}, {"name": "bad", "mac": "nope"}, "junk",
                   {"mac": "aa:bb:cc:dd:ee:03", "broadcast": "192.168.1.255", "port": 7}]}
    t = wol.targets(cfg)
    assert [(x["id"], x["name"]) for x in t] == [(0, "A"), (3, "aa:bb:cc:dd:ee:03")]
    assert t[1]["broadcast"] == "192.168.1.255" and t[1]["port"] == 7 and t[0]["port"] == 9


def test_wol_send_reaches_the_socket():
    import importlib
    import socket as so
    real = importlib.reload(wol)  # the demo replaces send(); the next demo app patches it again
    with so.socket(so.AF_INET, so.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        real.send({"mac": "aa:bb:cc:dd:ee:ff", "broadcast": "127.0.0.1", "port": rx.getsockname()[1]})
        assert rx.recv(200) == real.magic_packet("aa:bb:cc:dd:ee:ff")
