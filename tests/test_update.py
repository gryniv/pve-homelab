"""The updater: pinned commit, atomic swap, health check and rollback. No network, no root:
download, install.sh, the health check and systemctl are replaced by stand-ins over a temp dir."""

import json
import os

import pytest

from pvehomelab import config, update

OLD, NEW = "a" * 40, "b" * 40


@pytest.fixture
def host(tmp_path, monkeypatch):
    inst = tmp_path / "opt" / "pve-homelab"
    inst.mkdir(parents=True)
    (inst / "VERSION").write_text("0.4.0")
    (inst / "COMMIT").write_text(OLD)
    monkeypatch.setattr(update, "INSTALL_DIR", str(inst))
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "etc"))
    restarts = []
    monkeypatch.setattr(update, "_restart", lambda: restarts.append(1))

    async def fake_status(cfg):
        return {"latest": {"ref": "v0.5.0", "commit": NEW, "version": "0.5.0"}}
    monkeypatch.setattr(update, "status", fake_status)
    monkeypatch.setattr(update, "_download", lambda repo, commit, work: str(tmp_path))
    return {"inst": inst, "restarts": restarts, "tmp": tmp_path}


def swap_in(inst, version="0.5.0", commit=NEW):
    """What install.sh does: new version next to the old one, old one kept as .prev."""
    new = inst.parent / "pve-homelab.new"
    new.mkdir()
    (new / "VERSION").write_text(version)
    (new / "COMMIT").write_text(commit)
    os.rename(inst, str(inst) + ".prev")
    os.rename(new, inst)


CFG = {"update": {"repo": "gryniv/pve-homelab"}, "listen": "127.0.0.1:8900"}


def test_success_keeps_the_new_version(host, monkeypatch):
    monkeypatch.setattr(update, "_install", lambda src, env: swap_in(host["inst"]))
    monkeypatch.setattr(update, "_healthy", lambda cfg, want: True)
    update.apply(CFG)
    assert (host["inst"] / "VERSION").read_text() == "0.5.0"
    assert update.last_result()["ok"] is True and update.last_result()["commit"] == NEW


def test_new_version_that_does_not_start_is_rolled_back(host, monkeypatch):
    monkeypatch.setattr(update, "_install", lambda src, env: swap_in(host["inst"]))
    monkeypatch.setattr(update, "_healthy", lambda cfg, want: False)
    with pytest.raises(SystemExit):
        update.apply(CFG)
    assert (host["inst"] / "VERSION").read_text() == "0.4.0"
    assert (host["tmp"] / "opt" / "pve-homelab.failed" / "VERSION").read_text() == "0.5.0"
    r = update.last_result()
    assert r["ok"] is False and r["rolled_back"] is True and host["restarts"]


def test_install_failing_before_the_swap_changes_nothing(host, monkeypatch):
    def boom(src, env):
        raise RuntimeError("apt failed")
    monkeypatch.setattr(update, "_install", boom)
    with pytest.raises(RuntimeError):
        update.apply(CFG)
    assert (host["inst"] / "VERSION").read_text() == "0.4.0"
    r = update.last_result()
    assert r["ok"] is False and r["rolled_back"] is False and "apt failed" in r["error"]
    assert not host["restarts"]


def test_install_failing_after_the_swap_is_rolled_back(host, monkeypatch):
    def half(src, env):
        swap_in(host["inst"])
        raise RuntimeError("systemctl failed")
    monkeypatch.setattr(update, "_install", half)
    with pytest.raises(RuntimeError):
        update.apply(CFG)
    assert (host["inst"] / "VERSION").read_text() == "0.4.0"
    assert update.last_result()["rolled_back"] is True


def test_installer_gets_the_pinned_commit(host, monkeypatch):
    seen = {}
    monkeypatch.setattr(update, "_install", lambda src, env: (seen.update(env), swap_in(host["inst"])))
    monkeypatch.setattr(update, "_healthy", lambda cfg, want: seen.setdefault("want", want) and True)
    update.apply(CFG)
    assert seen["PVEHOMELAB_COMMIT"] == NEW and seen["want"] == NEW


def test_archive_root_must_be_the_commit(tmp_path):
    (tmp_path / f"pve-homelab-{NEW}").mkdir()
    assert update.archive_root(str(tmp_path), NEW).endswith(NEW)
    with pytest.raises(RuntimeError):
        update.archive_root(str(tmp_path), OLD)
    (tmp_path / "other").mkdir()
    with pytest.raises(RuntimeError):
        update.archive_root(str(tmp_path), NEW)


def test_rollback_without_previous_version(host):
    assert update.rollback() is False
    assert (host["inst"] / "VERSION").read_text() == "0.4.0"


def test_auto_ignores_main_channel_unless_allowed(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(update, "apply", lambda cfg, ref=None: called.append(1))
    monkeypatch.setattr(update.config, "load", lambda: {"update": {"repo": "x/y", "channel": "main", "auto": True}})
    monkeypatch.setattr("sys.argv", ["update", "auto"])
    update.main()
    assert not called and "auto_main" in capsys.readouterr().out


def test_result_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    assert update.last_result() is None
    update._save_result(ref="v1", ok=True)
    assert json.loads((tmp_path / update.RESULT_FILE).read_text())["ref"] == "v1"


def test_healthy_waits_for_the_new_commit():
    import http.server
    import threading
    answers = iter([OLD, OLD, NEW])

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "commit": next(answers, NEW)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = {"listen": f"127.0.0.1:{srv.server_port}"}
        assert update._healthy(cfg, NEW, timeout=3, interval=0.05)
        assert not update._healthy(cfg, "c" * 40, timeout=0.3, interval=0.05)
    finally:
        srv.shutdown()


def test_healthy_false_when_nothing_listens():
    assert not update._healthy({"listen": "127.0.0.1:9"}, NEW, timeout=0.3, interval=0.05)
