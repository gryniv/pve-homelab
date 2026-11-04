from conftest import login


async def test_foreign_host_refused(client):
    r = await client.get("/api/public", headers={"Host": "evil.example:8900", "X-Seat": "igpu"})
    assert r.status == 421


async def test_loopback_hosts_allowed(client):
    for host in ("127.0.0.1:8900", "localhost:8900", "[::1]:8900"):
        r = await client.get("/api/public", headers={"Host": host, "X-Seat": "igpu"})
        assert r.status == 200, host


async def test_cross_origin_post_refused(client):
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"},
                          headers={"Origin": "http://evil.example", "X-Seat": "igpu"})
    assert r.status == 403


async def test_same_origin_post_allowed(client):
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"},
                          headers={"Origin": "http://127.0.0.1:8900", "X-Seat": "igpu"})
    assert r.status == 200


async def test_allowed_hosts_star_turns_check_off(client):
    client.server.app["allowed_hosts_cache"].add("*")
    r = await client.get("/api/public", headers={"Host": "anything:8900", "X-Seat": "igpu"})
    assert r.status == 200


async def test_login_rate_limit(client):
    # The demo refuses an empty user name, like a wrong password.
    codes = [(await client.post("/api/login", json={"user": "", "password": "x"}, headers={"X-Seat": "igpu"})).status
             for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    # Another user name is not affected.
    await login(client)


async def test_housekeeping_forgets_stale_state(client):
    from pvehomelab import app as A
    from pvehomelab.launch import Job
    await login(client)
    app = client.server.app
    now = 1_000_000.0
    app["sessions"]["old"] = {"seen": now - A.SESSION_IDLE - 1}
    app["sessions"]["new"] = {"seen": now}
    app["consoles"]["old"] = {"at": now - A.CONSOLE_TOKEN_TTL - 1}
    old_job, live_job = Job([]), Job([])
    old_job.done, old_job.created = True, now - A.JOB_TTL - 1
    live_job.created = now - A.JOB_TTL - 1  # still running: kept
    app["launcher"].jobs.update({old_job.id: old_job, live_job.id: live_job})
    app["login_fails"]["x"] = [now - A.LOGIN_WINDOW - 1]
    A.housekeeping(app, now)
    assert "old" not in app["sessions"] and "new" in app["sessions"]
    assert "old" not in app["consoles"]
    assert old_job.id not in app["launcher"].jobs and live_job.id in app["launcher"].jobs
    assert "x" not in app["login_fails"]


def test_weather_cache_bounded():
    from pvehomelab import weather
    weather._cache.clear()
    for i in range(weather.MAX_ENTRIES + 10):
        weather._put(weather._cache, i, i)
    assert len(weather._cache) == weather.MAX_ENTRIES
    assert 0 not in weather._cache and weather.MAX_ENTRIES + 9 in weather._cache


# ---------- a second factor (Proxmox TOTP / recovery keys) ----------
import pytest  # noqa: E402

from pvehomelab.pve import parse_challenge  # noqa: E402


@pytest.mark.parametrize("partial,methods", [
    ("PVE:olena@pve:!tfa!%7B%22totp%22%3Atrue%2C%22recovery%22%3A%22available%22%7D:6560A1B2::sig", ["totp", "recovery"]),
    ("PVE:a@pve:!tfa!%7B%22webauthn%22%3A%7B%22challenge%22%3A%22x%22%7D%7D:1::s", ["webauthn"]),
    ("PVE:a@pve:!tfa!%7B%22totp%22%3Atrue%2C%22recovery%22%3A%22unavailable%22%2C%22yubico%22%3Atrue%7D:1::s", ["totp", "yubico"]),
    ("garbage", ["totp", "recovery"]),
])
def test_parse_challenge(partial, methods):
    assert parse_challenge(partial) == methods


async def _password(client, user="olena@pve", headers=None):
    r = await client.post("/api/login", json={"user": user, "password": "x"}, headers=headers or {"X-Seat": "igpu"})
    assert r.status == 200, await r.text()
    return r


async def test_a_code_after_the_password(client):
    r = await _password(client)
    d = await r.json()
    assert "Set-Cookie" not in r.headers and d["tfa"]["methods"] == ["totp", "recovery"]
    assert (await client.get("/api/me")).status == 401                     # not signed in yet
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "totp", "code": "123 456"}, headers={"X-Seat": "igpu"})
    assert r.status == 200 and (await r.json())["user"] == "olena@pve"
    assert (await client.get("/api/me")).status == 200
    # the challenge is spent
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "totp", "code": "123456"}, headers={"X-Seat": "igpu"})
    assert r.status == 404


async def test_a_recovery_key(client):
    d = await (await _password(client)).json()
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "recovery", "code": "demo-1111-2222"}, headers={"X-Seat": "igpu"})
    assert r.status == 200


async def test_wrong_codes_end_the_challenge(client):
    d = await (await _password(client)).json()
    cid = d["tfa"]["id"]
    for _ in range(4):
        r = await client.post("/api/login/tfa", json={"id": cid, "kind": "totp", "code": "000000"}, headers={"X-Seat": "igpu"})
        assert r.status == 401
    r = await client.post("/api/login/tfa", json={"id": cid, "kind": "totp", "code": "000000"}, headers={"X-Seat": "igpu"})
    assert r.status == 410                               # the fifth wrong code ends it
    assert cid not in client.server.app["tfa"]


async def test_a_challenge_stays_where_it_started(client):
    d = await (await _password(client)).json()
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "totp", "code": "123456"}, headers={"X-Seat": "web"})
    # X-Seat can't make the host's screen another seat, but a different seat id must not match either way
    c = client.server.app["tfa"][d["tfa"]["id"]]
    c["seat"] = "other"
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "totp", "code": "123456"}, headers={"X-Seat": "igpu"})
    assert r.status == 404


async def test_an_old_challenge_is_gone(client):
    d = await (await _password(client)).json()
    client.server.app["tfa"][d["tfa"]["id"]]["until"] = 0
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "totp", "code": "123456"}, headers={"X-Seat": "igpu"})
    assert r.status == 410


async def test_a_kind_the_account_lacks_is_refused(client):
    d = await (await _password(client)).json()
    r = await client.post("/api/login/tfa", json={"id": d["tfa"]["id"], "kind": "webauthn", "code": "{}"}, headers={"X-Seat": "igpu"})
    assert r.status == 400


async def test_limit_per_place_across_names(client):
    import time
    r = await client.post("/api/login", json={"user": "", "password": "x"}, headers={"X-Seat": "igpu"})
    assert r.status == 401
    fails = client.server.app["login_fails"]
    assert len(fails["seat:igpu"]) == 1                 # counted for the screen as well as the name
    fails["seat:igpu"] = [time.time()] * 20             # twenty wrong answers here, under any names
    r = await client.post("/api/login", json={"user": "ihor@pve", "password": "x"}, headers={"X-Seat": "igpu"})
    assert r.status == 429
