"""Designs: built-in looks in designs/, your own in the user folder, served at the old URLs."""

import os

import pytest

from pvehomelab import config, designs

from conftest import ROOT

SEAT = {"X-Seat": "igpu"}


@pytest.fixture
def mine(tmp_path, monkeypatch):
    """An empty user designs folder for the test."""
    monkeypatch.setattr(config, "USER_DESIGNS_DIR", str(tmp_path))
    return tmp_path


def write(root, kind, name, text):
    os.makedirs(root / kind, exist_ok=True)
    (root / kind / name).write_text(text, encoding="utf-8")


def test_builtin_designs_are_found():
    ids = {k: [m["id"] for m in designs.catalog(k)] for k in designs.KINDS}
    assert {"dusk", "forest", "graphite", "ice"} <= set(ids["themes"])
    assert "mountains" in ids["backgrounds"] and "flip" in ids["clocks"] and "onest" in ids["fonts"]
    assert "host" in ids["widgets"]
    assert all(m["source"] == "builtin" for m in designs.catalog("themes"))


def test_header_metadata():
    dusk = next(m for m in designs.catalog("themes") if m["id"] == "dusk")
    assert dusk["name"]["en"] and dusk["name"]["uk"]


def test_user_design_is_added_and_replaces_builtin(mine):
    write(mine, "themes", "my-theme.css", "/*\n * @name.en Mine\n * @order 1\n */\n:root{--acc:#f0f}")
    write(mine, "themes", "dusk.css", "/* @name.en My dusk */")
    themes = {m["id"]: m for m in designs.catalog("themes")}
    assert themes["my-theme"]["source"] == "user" and themes["my-theme"]["name"]["en"] == "Mine"
    assert themes["dusk"]["source"] == "user" and themes["dusk"]["replaces"] == "builtin"
    assert designs.catalog("themes")[0]["id"] == "my-theme"  # @order 1 first
    assert designs.path_of("themes", "dusk") == str(mine / "themes" / "dusk.css")


def test_bad_names_are_ignored(mine):
    write(mine, "themes", "Bad Name.css", "")
    write(mine, "themes", "x.js", "")
    write(mine, "themes", ".hidden.css", "")
    assert not {"Bad Name", "x", ".hidden"} & {m["id"] for m in designs.catalog("themes")}
    assert designs.path_of("themes", "../../etc/passwd") is None
    assert designs.path_of("nope", "dusk") is None


async def test_served_at_the_old_urls(client):
    for url, ctype in (("/themes/dusk.css", "text/css"), ("/backgrounds/mountains.css", "text/css"),
                       ("/fonts/onest.css", "text/css"), ("/widgets/host/widget.css", "text/css"),
                       ("/clocks/flip.js", "javascript")):
        r = await client.get(url)
        assert r.status == 200, url
        assert ctype in r.headers["Content-Type"], (url, r.headers["Content-Type"])
    assert (await client.get("/widgets/host/widget.js")).status == 200   # the widget's logic stays in web/


async def test_user_design_served_first(client, mine):
    write(mine, "themes", "dusk.css", "/* mine */ :root{--acc:#123456}")
    write(mine, "widgets", "host.css", ".A .w[data-w=host]{outline:1px solid red}")
    assert "#123456" in await (await client.get("/themes/dusk.css")).text()
    assert "outline" in await (await client.get("/widgets/host/widget.css")).text()


async def test_missing_and_traversal_are_404(client):
    for url in ("/themes/nope.css", "/themes/..%2F..%2Fconfig.css", "/clocks/UPPER.js", "/widgets/nope/widget.css"):
        assert (await client.get(url)).status == 404, url


async def test_public_lists_designs_and_widget_styles(client, mine):
    write(mine, "backgrounds", "my-bg.css", "/*\n * @name.en My background\n * @group flat\n */")
    pub = await (await client.get("/api/public", headers=SEAT)).json()
    assert any(m["id"] == "my-bg" and m["source"] == "user" for m in pub["backgrounds"])
    assert "host" in pub["widget_styles"] and "weather" in pub["widget_styles"]


def test_designs_folder_has_no_program_code():
    """designs/ holds looks only: stylesheets, and clocks (small ES modules)."""
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "designs")):
        kind = os.path.basename(dirpath)
        for f in files:
            assert f.endswith("." + designs.KINDS[kind]), os.path.join(dirpath, f)
