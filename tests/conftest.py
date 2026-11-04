"""Test set-up: the backend runs as the demo (a made-up host kept in memory), with its state in a
temporary directory. Paths are read when pvehomelab is imported, so the environment is set first."""

import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = tempfile.mkdtemp(prefix="pvehomelab-test-")
os.environ["PVEHOMELAB_CONFIG"] = os.path.join(ROOT, "etc", "demo.yaml")
os.environ["PVEHOMELAB_WEB"] = os.path.join(ROOT, "web")
os.environ["PVEHOMELAB_DESIGNS"] = os.path.join(ROOT, "designs")
os.environ["PVEHOMELAB_STATE"] = os.path.join(STATE, "state")
os.environ["PVEHOMELAB_CACHE"] = os.path.join(STATE, "cache")
os.environ["PVEHOMELAB_INSTALL"] = ROOT
sys.path.insert(0, os.path.join(ROOT, "backend"))

from pvehomelab import demo  # noqa: E402  (after the environment above)

# The demo world as shipped; every test starts from it (make_app would snapshot the current one).
PRISTINE = demo._snapshot()

@pytest.fixture
def state_dir():
    return os.environ["PVEHOMELAB_STATE"]


@pytest.fixture(autouse=True)
def _clean_state():
    shutil.rmtree(os.environ["PVEHOMELAB_STATE"], ignore_errors=True)
    yield


@pytest.fixture
async def client(aiohttp_client):
    c = await aiohttp_client(demo.make_app())
    demo._initial = PRISTINE
    await c.post("/api/demo/reset", json={})
    return c


async def login(client, user="ihor@pve"):
    r = await client.post("/api/login", json={"user": user, "password": "x"}, headers={"X-Seat": "igpu"})
    assert r.status == 200, await r.text()
    return await r.json()
