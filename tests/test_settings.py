"""Settings → System: the registry covers config.DEFAULTS, the menu's changes win over config.yaml
and take effect, wrong values are refused, and only admins get there."""

import json
import os

import pytest
import yaml

from pvehomelab import config, settings, update

from conftest import login

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leaves(d, prefix=""):
    for k, v in d.items():
        p = prefix + k
        if isinstance(v, dict) and v:
            yield from _leaves(v, p + ".")
        else:
            yield p


def test_every_option_is_in_the_menu_or_says_why_not():
    covered = set(settings.BY_PATH) | set(settings.NOT_IN_MENU)
    missing = [p for p in _leaves(config.DEFAULTS)
               if not any(p == c or p.startswith(c + ".") for c in covered)]
    assert missing == []


def _strings(lang):
    with open(os.path.join(ROOT, "web", "i18n", f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_every_setting_has_a_name(lang):
    s = _strings(lang)
    assert [p for p in settings.BY_PATH if f"cfg.{p}" not in s] == []
    assert [g for g in settings.GROUPS if f"cfg.g.{g}" not in s] == []
    fields = {f[0] for x in settings.REGISTRY for f in x.fields}
    assert [f for f in fields if f"cfg.f.{f}" not in s] == []
    # no names left for settings that are gone
    ui = ("cfg.g.", "cfg.f.", "cfg.src_", "cfg.reset_", "cfg.restart", "cfg.row_")
    plain = {"cfg.lead", "cfg.search", "cfg.nothing", "cfg.elsewhere", "cfg.needs_restart", "cfg.invalid", "cfg.one_per_line"}
    stale = []
    for k in s:
        if not k.startswith("cfg.") or k.startswith(ui) or k in plain:
            continue
        rest = k[4:].removesuffix("_hint")
        if rest not in settings.BY_PATH and rest.rsplit(".", 1)[0] not in settings.BY_PATH:
            stale.append(k)
    assert stale == []


@pytest.mark.parametrize("path,value,kept", [
    ("alerts.storage_pct", "85", 85),
    ("web.allow_from", "192.168.8.150, 10.0.0.0/24", ["192.168.8.150", "10.0.0.0/24"]),
    ("web.sign_in", "users", "users"),
    ("systems_extra", ["100", 101], [100, 101]),
    ("caddy.ct", None, None),
    ("wol", [{"name": "NAS", "mac": "AA-BB-CC-DD-EE-FF", "port": "9"}], [{"name": "NAS", "mac": "aa:bb:cc:dd:ee:ff", "port": 9}]),
    ("services", {"ct206-3000": {"name": "DNS", "icon": ""}}, {"ct206-3000": {"name": "DNS"}}),
    ("listen", "0.0.0.0:8900", "0.0.0.0:8900"),
])
def test_values_are_kept_in_their_form(path, value, kept):
    assert settings.check(path, value) == kept


@pytest.mark.parametrize("path,value", [
    ("alerts.storage_pct", 30), ("alerts.storage_pct", True), ("web.sign_in", "all"), ("web.allow_from", ["not a net"]),
    ("systems_extra", [5]), ("links", [{"name": "x", "url": "javascript:alert(1)"}]), ("links", [{"name": "x"}]),
    ("wol", [{"name": "x", "mac": "zz"}]), ("listen", "8900"), ("node", "a b"), ("weather.city", "x\ny"),
    ("nothing.here", 1), ("update.repo", "../etc"),
])
def test_wrong_values_are_refused(path, value):
    with pytest.raises(settings.Invalid):
        settings.check(path, value)


def test_menu_wins_over_the_file_and_a_reset_goes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("alerts: {temp_c: 70}\nweather: {city: Lviv}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(cfg_file))
    over, errors = settings.change({"alerts.temp_c": 90, "web.sign_in": "full"})
    assert errors == {} and over == {"alerts": {"temp_c": 90}, "web": {"sign_in": "full"}}
    cfg = config.load()
    assert cfg["alerts"]["temp_c"] == 90 and cfg["weather"]["city"] == "Lviv" and cfg["web"]["sign_in"] == "full"
    form = {s["path"]: s for s in settings.describe(config.load_file(), settings.load_overlay())}
    assert form["alerts.temp_c"]["source"] == "menu" and form["alerts.temp_c"]["file_value"] == 70
    assert form["weather.city"]["source"] == "file" and form["lock_after_min"]["source"] == "default"
    settings.change(resets=["alerts.temp_c", "web.sign_in"])
    assert config.load()["alerts"]["temp_c"] == 70
    assert settings.load_overlay() == {}
    # a wrong value writes nothing at all
    over, errors = settings.change({"alerts.temp_c": 500, "lock_after_min": 5})
    assert "alerts.temp_c" in errors and settings.load_overlay() == {}


def test_a_bad_line_in_settings_yaml_costs_only_that_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    (tmp_path / settings.FILE).write_text("alerts: {temp_c: hot, storage_pct: 80}\nweird: 1\n", encoding="utf-8")
    assert settings.load_overlay() == {"alerts": {"storage_pct": 80}}
    (tmp_path / settings.FILE).write_text("{{{", encoding="utf-8")
    assert settings.load_overlay() == {}


def test_automatic_updates_live_in_the_same_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    (tmp_path / update.MENU_FILE).write_text('{"auto": true}', encoding="utf-8")   # kept there before 0.8
    assert update.settings({"update": {"auto": False}})["auto"] is True
    update.set_auto(False)
    assert not (tmp_path / update.MENU_FILE).exists()
    assert yaml.safe_load((tmp_path / settings.FILE).read_text(encoding="utf-8")) == {"update": {"auto": False}}
    assert update.settings({"update": {"auto": True}})["auto"] is False


# ---------- the API ----------
async def test_only_admins(client):
    assert (await client.get("/api/system/settings")).status == 401
    await login(client, "guest@pve")
    assert (await client.get("/api/system/settings")).status == 403
    assert (await client.put("/api/system/settings", json={"set": {"alerts.temp_c": 70}})).status == 403


async def test_a_change_takes_effect_at_once(client):
    await login(client)
    form = await (await client.get("/api/system/settings")).json()
    assert "alerts" in form["groups"] and any(s["path"] == "alerts.storage_pct" for s in form["settings"])
    r = await client.put("/api/system/settings", json={"set": {"alerts.storage_pct": 55, "weather.city": "Odesa"}})
    assert r.status == 200
    cfg = client.server.app["cfg"]
    assert cfg["alerts"]["storage_pct"] == 55 and cfg["weather"]["city"] == "Odesa"
    s = {x["path"]: x for x in (await r.json())["settings"]}
    assert s["alerts.storage_pct"]["source"] == "menu" and s["alerts.storage_pct"]["value"] == 55
    r = await client.put("/api/system/settings", json={"reset": ["alerts.storage_pct"]})
    assert client.server.app["cfg"]["alerts"]["storage_pct"] == 90


async def test_wrong_values_say_which(client):
    await login(client)
    r = await client.put("/api/system/settings", json={"set": {"alerts.storage_pct": 5, "lock_after_min": 3}})
    assert r.status == 400
    d = await r.json()
    assert set(d["errors"]) == {"alerts.storage_pct"} and d["error"]
    assert client.server.app["cfg"]["lock_after_min"] != 3      # nothing applied
    assert (await client.put("/api/system/settings", json=["x"])).status == 400


async def test_some_changes_need_a_restart(client):
    await login(client)
    form = await (await client.put("/api/system/settings", json={"set": {"kiosk.debug_port": 9222}})).json()
    assert form["restart"] == "kiosk"
    form = await (await client.put("/api/system/settings", json={"set": {"update.check_hours": 12}})).json()
    assert form["restart"] == "all"
    r = await client.post("/api/system/restart")
    assert r.status == 200 and (await r.json())["restarting"] == "all"
    assert (await (await client.get("/api/system/settings")).json())["restart"] is None


# ---------- Components: a part switched off is gone from the API ----------
@pytest.mark.parametrize("feature,method,path", [
    ("alerts", "GET", "/api/alerts"),
    ("node_updates", "GET", "/api/node-updates"),
    ("app_updates", "POST", "/api/update/check"),
    ("weather", "GET", "/api/weather"),
    ("wol", "GET", "/api/wol"),
    ("guest_actions", "POST", "/api/guests/lxc/201/shutdown"),
    ("host_power", "POST", "/api/host/power"),
    ("my_widgets", "DELETE", "/api/widgets/x"),
])
async def test_a_switched_off_part_answers_404(client, feature, method, path):
    await login(client)
    r = await client.put("/api/system/settings", json={"set": {f"features.{feature}": False}})
    assert r.status == 200
    pub = await (await client.get("/api/public", headers={"X-Seat": "igpu"})).json()
    assert pub["features"][feature] is False
    r = await client.request(method, path, json={})
    assert r.status == 404 and (await r.json())["error"]
    await client.put("/api/system/settings", json={"reset": [f"features.{feature}"]})
    assert (await (await client.get("/api/public", headers={"X-Seat": "igpu"})).json())["features"][feature] is True


async def test_guest_details_stay_when_actions_are_off(client):
    await login(client)
    await client.put("/api/system/settings", json={"set": {"features.guest_actions": False}})
    assert (await client.get("/api/guests")).status == 200
    assert (await client.get("/api/guests/lxc/201/info")).status == 200
