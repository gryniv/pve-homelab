"""A copy of the menu's settings: taken, checked, put back part by part, and never anything else."""

import hashlib
import io
import json
import os
import tarfile

import pytest

from pvehomelab import backup, config

from conftest import login


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A /etc/pve-homelab of its own."""
    st = tmp_path / "etc"
    (st / "users").mkdir(parents=True)
    (st / "designs" / "themes").mkdir(parents=True)
    (st / "widgets" / "hello").mkdir(parents=True)
    (st / "launch").mkdir()
    monkeypatch.setattr(config, "STATE_DIR", str(st))
    monkeypatch.setattr(config, "USER_DESIGNS_DIR", str(st / "designs"))
    monkeypatch.setattr(config, "USER_WIDGETS_DIR", str(st / "widgets"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(st / "config.yaml"))
    (st / "config.yaml").write_text("node: pve\ncaddy: {ct: 200}\nhome_assistant: {token: abc123}\n", encoding="utf-8")
    (st / "users" / "ihor@pve.yaml").write_text("skin: forest\n", encoding="utf-8")
    (st / "login.yaml").write_text("title: Home\n", encoding="utf-8")
    (st / "settings.yaml").write_text("alerts: {temp_c: 70}\n", encoding="utf-8")
    (st / "designs" / "themes" / "mine.css").write_text("/* @kind theme */", encoding="utf-8")
    (st / "widgets" / "hello" / "widget.js").write_text("export default {}", encoding="utf-8")
    (st / "launch" / "102.json").write_text('{"hostpci": {}}', encoding="utf-8")
    (st / "update-result.json").write_text("{}", encoding="utf-8")       # not a setting
    return st


def test_a_copy_and_back(host):
    blob = backup.export(version="0.8.0")
    names = set(backup.read(blob)[1])
    assert names == {"config.yaml", "users/ihor@pve.yaml", "login.yaml", "settings.yaml", "designs/themes/mine.css",
                     "widgets/hello/widget.js", "launch/102.json"}
    (host / "users" / "ihor@pve.yaml").write_text("skin: dusk\n", encoding="utf-8")
    (host / "login.yaml").unlink()
    p = backup.plan(blob)
    assert p["parts"]["users"] == {"new": 0, "changed": 1, "same": 0} and p["parts"]["host"]["new"] == 1
    snap, written = backup.apply(blob, ["users", "host"])
    assert (host / "users" / "ihor@pve.yaml").read_text(encoding="utf-8") == "skin: forest\n"
    assert (host / "login.yaml").exists() and "config.yaml" not in written
    assert os.path.exists(snap)                                     # what was there before is kept


def test_no_secrets_in_a_copy(host):
    files = backup.read(backup.export())[1]
    assert b"abc123" not in files["config.yaml"] and b"ct: 200" in files["config.yaml"]


def test_five_snapshots_are_kept(host):
    blob = backup.export()
    for i in range(7):
        snap, _ = backup.apply(blob, ["users"])
        os.rename(snap, snap.replace("pre-import-", f"pre-import-{i:02d}-"))
    assert len(os.listdir(host / "backups")) == 5


def _tar(entries, manifest=True):
    buf = io.BytesIO()
    files = {n: d for n, d, _ in entries if isinstance(d, bytes)}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if manifest:
            m = json.dumps({"format": 1, "app": "pve-homelab", "files": {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}}).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(m)
            tar.addfile(info, io.BytesIO(m))
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/shadow"
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("entries,manifest", [
    ([("../../etc/cron.d/x", b"x", "file")], True),
    ([("/etc/passwd", b"x", "file")], True),
    ([("users/a.yaml", None, "link")], True),
    ([("users/a.yaml", b"skin: x", "file")], False),
    ([("pve-homelab.service", b"x", "file")], True),
    ([("users/a.yaml", b"- a list", "file")], True),
    ([("designs/themes/x.exe", b"x", "file")], True),
])
def test_odd_copies_are_refused(host, entries, manifest):
    with pytest.raises(backup.BadCopy):
        backup.read(_tar(entries, manifest))


def test_a_changed_file_is_refused(host):
    blob = _tar([("users/a.yaml", b"skin: x", "file")])
    backup.read(blob)
    buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as src, tarfile.open(fileobj=buf, mode="w:gz") as dst:
        for m in src:
            data = src.extractfile(m).read()
            if m.name == "users/a.yaml":
                data = b"skin: y"
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    with pytest.raises(backup.BadCopy):
        backup.read(buf.getvalue())
    with pytest.raises(backup.BadCopy):
        backup.read(b"not a tar")


# ---------- the API ----------
async def test_copy_through_the_menu(client):
    assert (await client.get("/api/backup/export")).status == 401
    await login(client, "guest@pve")
    assert (await client.get("/api/backup/export")).status == 403
    await login(client)
    await client.put("/api/prefs", json={"skin": "forest"})
    r = await client.get("/api/backup/export")
    assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]
    blob = await r.read()
    await client.put("/api/prefs", json={"skin": "graphite"})
    import aiohttp
    form = aiohttp.FormData()
    form.add_field("file", blob, filename="copy.tar.gz", content_type="application/gzip")
    r = await client.post("/api/backup/inspect", data=form)
    assert r.status == 200, await r.text()
    d = await r.json()
    assert d["parts"]["users"]["changed"] >= 1 and d["token"]
    r = await client.post("/api/backup/apply", json={"token": d["token"], "parts": ["users"]})
    assert r.status == 200 and (await r.json())["written"] >= 1
    assert (await (await client.get("/api/me")).json())["prefs"]["skin"] == "forest"
    # a token is used once
    assert (await client.post("/api/backup/apply", json={"token": d["token"], "parts": ["users"]})).status == 410


async def test_a_bad_copy_is_named(client):
    await login(client)
    import aiohttp
    form = aiohttp.FormData()
    form.add_field("file", b"junk", filename="copy.tar.gz")
    r = await client.post("/api/backup/inspect", data=form)
    assert r.status == 400 and "tar" in (await r.json())["error"]
