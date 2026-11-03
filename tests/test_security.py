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
