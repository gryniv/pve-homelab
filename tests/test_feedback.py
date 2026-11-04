"""Writing to the author: what goes into the issue, what is taken out, and who may add what."""

from urllib.parse import parse_qs, urlparse

from pvehomelab import app as A, errlog, feedback

from conftest import login

SEAT = {"X-Seat": "igpu"}


def test_scrub_takes_out_names_and_addresses():
    text = ("ihor@pve could not reach https://jellyfin.home.example:8096/web at 192.168.1.20:8096, "
            "fe80::1c2b:3cff:fe4d:5e6f, mac 52:54:00:12:34:56, /home/ihor/x, nas.lan, Ihor's win11-box on pve; "
            "at 10:20:30 GET /api/guests/qemu/101 returned 500 in app.js")
    known = [("pve", "<node>"), ("Ihor", "<user>"), ("win11-box", "<guest>")]
    out = feedback.scrub(text, known)
    for gone in ("ihor@pve", "jellyfin", "192.168", "fe80", "52:54", "/home/ihor", "nas.lan", "Ihor", "win11-box", " pve;"):
        assert gone not in out, (gone, out)
    for kept in ("10:20:30", "/api/guests/qemu/101", "returned 500", "app.js", "https://<host>/web", "<guest>", "<node>"):
        assert kept in out, (kept, out)


def test_journal_lines_are_short_and_clean():
    entries = [{"last": 0, "level": "error", "source": "client:js", "count": 3, "where": "ihor@pve on igpu",
                "msg": "x " * 400}, {"time": 0, "level": "warning", "source": "server", "msg": "ok at 10.0.0.5"}]
    lines = feedback.journal_lines(entries)
    assert len(lines) == 2 and "×3" in lines[0] and "<user>" in lines[0] and len(lines[0]) < 320
    assert lines[1].endswith("ok at <ip>")


def test_browser_and_environment():
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    assert feedback.browser(ua) == "Chrome 142 on Linux"
    assert feedback.browser("") == "unknown"
    env = feedback.environment({"version": "0.5.0", "commit": "0db35ea1234"}, "8.4.1",
                               {"ua": ua, "screen": "1920x1080", "lang": "uk"})
    assert env[0] == "PVE Homelab 0.5.0 (0db35ea)" and env[1] == "Proxmox VE 8.4.1"
    assert "Screen: 1920×1080" in env and "Language: uk" in env
    odd = feedback.environment({}, "", {"screen": "<script>", "lang": "../../x"})
    assert not any("script" in x or "../" in x for x in odd)


def test_compose_link_and_qr():
    r = feedback.compose("gryniv/pve-homelab", "idea", "Dark  mode\nfor the clock", "Please.", env=["Proxmox VE 8"])
    assert r["title"] == "Idea: Dark mode for the clock"
    u = urlparse(r["url"])
    assert (u.netloc, u.path) == ("github.com", "/gryniv/pve-homelab/issues/new")
    q = parse_qs(u.query)
    assert q["title"] == [r["title"]] and q["body"] == [r["body"]]
    assert r["body"].startswith("Please.") and "- Proxmox VE 8" in r["body"]
    assert r["qr"].startswith("<svg") and not r["too_long"]
    assert feedback.compose("o/r", "nope", "", "")["title"] == "Bug: "   # unknown kind: a bug


def test_journal_is_cut_to_fit_the_qr_code():
    lines = [f"2026-11-04 10:{i:02d} error server: something failed in a fairly long way number {i}" for i in range(10)]
    r = feedback.compose("o/r", "bug", "t", "x", journal=lines, journal_total=25)
    assert len(r["url"]) <= feedback.QR_MAX and r["qr"]
    assert 0 < r["journal_shown"] < 10 and r["journal_total"] == 25
    assert f"{25 - r['journal_shown']} more in Settings → About" in r["body"]
    assert lines[0] in r["body"] and lines[-1] not in r["body"]   # the newest stay


def test_empty_journal_says_so():
    assert "no errors recorded" in feedback.compose("o/r", "bug", "t", "x", journal=[])["body"]
    assert "Error journal" not in feedback.compose("o/r", "bug", "t", "x")["body"]   # not asked for


def test_long_text_gets_no_qr_but_a_link():
    r = feedback.compose("o/r", "bug", "t", "word " * 500)
    assert r["qr"] is None and r["url"] and not r["too_long"]
    r = feedback.compose("o/r", "bug", "t", "дуже довгий текст " * 300)   # 6 bytes per letter once encoded
    assert r["too_long"] and r["url"] is None


async def test_api_admin_with_journal(client):
    errlog.add("error", "server", "could not reach 192.168.1.50 for ihor@pve")
    await login(client)
    r = await client.post("/api/feedback", json={"kind": "bug", "title": "Launch fails", "text": "It fails.",
                                                 "env": True, "journal": True,
                                                 "client": {"ua": "Chrome/142 Linux", "screen": "1920x1080", "lang": "en"}})
    assert r.status == 200, await r.text()
    d = await r.json()
    assert d["journal_allowed"] and d["journal_shown"] >= 1 and d["qr"]
    assert "PVE Homelab" in d["body"] and "Proxmox VE" in d["body"] and "— demo" in d["body"]
    assert "could not reach <ip> for <user>" in d["body"]
    assert "ihor" not in d["body"].lower() and "192.168" not in d["body"]
    assert "/gryniv/pve-homelab/issues/new" in d["url"]


async def test_api_guest_gets_no_journal_and_nothing_extra_unasked(client):
    errlog.add("error", "server", "secret-ish failure")
    await login(client, "guest@pve")
    d = await (await client.post("/api/feedback", json={"kind": "question", "text": "How?", "journal": True})).json()
    assert d["journal_allowed"] is False and "secret-ish" not in d["body"]
    assert "Environment" not in d["body"]   # only what was asked for


async def test_api_needs_a_session_and_can_be_off(client, monkeypatch):
    assert (await client.post("/api/feedback", json={})).status == 401
    await login(client)
    monkeypatch.setitem(client.server.app["cfg"], "feedback", False)
    assert (await client.post("/api/feedback", json={})).status == 404
    pub = await (await client.get("/api/public", headers=SEAT)).json()
    assert pub["feedback"] is False
    monkeypatch.setitem(client.server.app["cfg"], "feedback", {"repo": "https://github.com/someone/fork.git"})
    d = await (await client.post("/api/feedback", json={"text": "hi"})).json()
    assert "/someone/fork/issues/new" in d["url"]


def test_feedback_cfg():
    assert A.feedback_cfg({}) == {"enabled": True, "repo": ""}
    assert A.feedback_cfg({"feedback": False})["enabled"] is False
    assert A.feedback_cfg({"feedback": {"enabled": False}})["enabled"] is False
    assert A.feedback_cfg({"feedback": "junk"}) == {"enabled": True, "repo": ""}
