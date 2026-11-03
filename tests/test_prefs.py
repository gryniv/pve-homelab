from pvehomelab import prefs

from conftest import login


def test_unknown_keys_dropped():
    assert "evil" not in prefs._merge(prefs.DEFAULT, {"evil": 1})


def test_wrong_types_keep_defaults():
    pr = prefs._merge(prefs.DEFAULT, {
        "layout": "oops", "widget_opts": [1], "avatar": "3", "show_on_login": "yes",
        "hidden_services": "x", "skin": 5, "launch": {"ask": "no"},
    })
    assert pr["layout"] == prefs.DEFAULT["layout"]
    assert pr["widget_opts"] == {}
    assert pr["avatar"] == 0
    assert pr["show_on_login"] is True
    assert pr["hidden_services"] == []
    assert pr["skin"] == "dusk"
    assert pr["launch"]["ask"] is True


def test_bool_is_not_an_int():
    assert prefs._merge(prefs.DEFAULT, {"avatar": True})["avatar"] == 0


def test_valid_values_kept():
    pr = prefs._merge(prefs.DEFAULT, {"skin": "forest", "avatar": 2, "hidden_systems": [101, "x"],
                                      "layout": {"login": ["clock"]}, "widget_opts": {"note": {"text": "hi"}}})
    assert pr["skin"] == "forest" and pr["avatar"] == 2 and pr["hidden_systems"] == [101, "x"]
    assert pr["layout"]["login"] == ["clock"] and pr["layout"]["side"] == prefs.DEFAULT["layout"]["side"]
    assert pr["widget_opts"] == {"note": {"text": "hi"}}


def test_sizes_capped():
    pr = prefs._merge(prefs.DEFAULT, {"note": "n" * 10000, "skin": "s" * 1000, "hidden_services": ["a"] * 1000})
    assert len(pr["note"]) == prefs.MAX_STR["note"]
    assert len(pr["skin"]) == prefs.MAX_STR_DEFAULT
    assert len(pr["hidden_services"]) == prefs.MAX_LIST


def test_not_a_dict():
    assert prefs._merge(prefs.DEFAULT, ["x"]) == prefs.DEFAULT
    assert prefs._merge(prefs.DEFAULT, None) == prefs.DEFAULT


def test_public_hides_private_widget_options():
    pr = prefs._merge(prefs.DEFAULT, {"layout": {"login": ["weather"]},
                                      "widget_opts": {"weather": {"days": 3}, "note": {"text": "secret"}}})
    assert prefs.public(pr)["widget_opts"] == {"weather": {"days": 3}}


async def test_bad_prefs_do_not_break_sign_in_screen(client):
    await login(client)
    r = await client.put("/api/prefs", json={"layout": "broken", "widget_opts": "broken"})
    assert r.status == 200
    r = await client.get("/api/public", headers={"X-Seat": "igpu"})
    assert r.status == 200
    users = (await r.json())["users"]
    assert any(u["id"] == "ihor@pve" for u in users)


async def test_prefs_body_must_be_an_object(client):
    await login(client)
    assert (await client.put("/api/prefs", data="nope", headers={"Content-Type": "application/json"})).status == 400
    assert (await client.put("/api/prefs", json=[1, 2])).status == 400
