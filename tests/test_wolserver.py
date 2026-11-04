"""A Wake-on-LAN packet starts a listed VM, and nothing else."""

import pytest

from pvehomelab import demo, wolserver

from conftest import login

PACKET = b"\xff" * 6 + bytes.fromhex("bc2411aabbcc") * 16


def test_parse_magic():
    assert wolserver.parse_magic(PACKET) == "bc:24:11:aa:bb:cc"
    assert wolserver.parse_magic(b"\x00junk" + PACKET + b"\x01\x02\x03\x04") == "bc:24:11:aa:bb:cc"   # with a SecureOn tail
    assert wolserver.parse_magic(b"\xff" * 6 + bytes.fromhex("bc2411aabbcc") * 15) is None
    assert wolserver.parse_magic(b"hello") is None


def test_vm_macs():
    confs = {"/etc/pve/qemu-server/102.conf": "net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0\nnet1: e1000=02:00:00:00:00:01,bridge=vmbr1\n"
                                              "[snap]\nnet0: virtio=11:11:11:11:11:11,bridge=vmbr0\n"}
    import glob as _g
    real = _g.glob
    wolserver.glob.glob = lambda pattern: list(confs)
    try:
        got = wolserver.vm_macs(read=lambda p: confs[p])
    finally:
        wolserver.glob.glob = real
    assert got == {"bc:24:11:aa:bb:cc": 102, "02:00:00:00:00:01": 102}


@pytest.fixture
def listening(client, monkeypatch):
    app = client.server.app
    monkeypatch.setitem(app["cfg"], "wol_listen", {"enabled": True, "vms": [102], "from": ["192.168.8.0/24"], "ports": [9]})
    srv = app["wolserver"]
    monkeypatch.setattr(srv, "macs", lambda: {"bc:24:11:aa:bb:cc": 102, "bc:24:11:00:00:01": 100})
    started = []

    async def start(endpoint, /, **kw):
        started.append(endpoint)
        demo.WORLD[int(endpoint.split("/")[4])]["status"] = "running"
    monkeypatch.setattr(wolserver, "pvesh_create", start)
    return srv, started


async def test_a_listed_vm_starts(client, listening):
    srv, started = listening
    assert await srv.packet(PACKET, "192.168.8.20") == 102
    assert started == ["/nodes/demo/qemu/102/status/start"]
    assert await srv.packet(PACKET, "192.168.8.20") is None        # running already, and once a minute at most


@pytest.mark.parametrize("data,ip", [
    (b"\xff" * 6 + bytes.fromhex("bc2411000001") * 16, "192.168.8.20"),   # VM 100: not listed
    (PACKET, "10.9.9.9"),                                                 # not from a listed network
    (b"\xff" * 6 + bytes.fromhex("aaaaaaaaaaaa") * 16, "192.168.8.20"),   # nobody's card
])
async def test_nothing_else_starts(client, listening, data, ip):
    srv, started = listening
    assert await srv.packet(data, ip) is None and started == []


async def test_a_busy_gpu_says_no(client, listening):
    srv, started = listening
    demo.WORLD[100].update(status="running", hostpci={0: "mapping=rtx,pcie=1"})   # VM 100 holds the RTX
    client.server.app["resources"].invalidate()
    assert await srv.packet(PACKET, "192.168.8.20") is None and started == []
