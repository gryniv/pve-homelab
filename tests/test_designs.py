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


# ---------------- installing from the menu ----------------
from aiohttp import FormData  # noqa: E402

from conftest import login  # noqa: E402

THEME = b"/*\n * @kind theme\n * @name.en Neon night\n */\n.A[data-skin=\"neon-night\"]{--acc:#0ff}\n"


def form(*files):
    f = FormData()
    for name, data in files:
        f.add_field("file", data, filename=name, content_type="application/octet-stream")
    return f


async def test_admin_installs_and_removes(client, mine):
    me = await login(client)
    assert (await (await client.get("/api/me")).json())["admin"] is True
    r = await client.post("/api/designs", data=form(("neon-night.css", THEME)))
    assert r.status == 200, await r.text()
    assert (await r.json())["installed"] == [{"kind": "themes", "id": "neon-night", "replaces": None}]
    assert (mine / "themes" / "neon-night.css").read_bytes() == THEME
    assert "#0ff" in await (await client.get("/themes/neon-night.css")).text()
    lst = await (await client.get("/api/designs")).json()
    assert [(d["kind"], d["id"]) for d in lst["mine"]] == [("themes", "neon-night")]
    assert (await client.delete("/api/designs/themes/neon-night")).status == 200
    assert not (mine / "themes" / "neon-night.css").exists()
    assert (await client.delete("/api/designs/themes/neon-night")).status == 404
    assert (await client.delete("/api/designs/themes/dusk")).status == 404   # built-in ones can't be removed
    assert me


async def test_zip_with_several_designs(client, mine):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pack/themes/aqua.css", "/* @name.en Aqua */ .A[data-skin=aqua]{}")
        z.writestr("pack/clocks/tiny.js", "export const css=''; export function render(el,t){el.textContent=t.text}")
        z.writestr("pack/widgets/host.css", ".A .w[data-w=host]{}")
        z.writestr("__MACOSX/._junk", "x")
    await login(client)
    r = await client.post("/api/designs", data=form(("pack.zip", buf.getvalue())))
    assert r.status == 200, await r.text()
    got = {(d["kind"], d["id"], d["replaces"]) for d in (await r.json())["installed"]}
    assert got == {("themes", "aqua", None), ("clocks", "tiny", None), ("widgets", "host", "builtin")}


async def test_bad_uploads_refused_and_nothing_written(client, mine):
    await login(client)
    for name, data in (("Bad Name.css", THEME), ("x.exe", b"MZ"), ("big.css", b"/* @kind theme */" + b" " * (designs.MAX_BYTES + 1)),
                       ("what.css", b"body{}"), ("bin.css", b"\xff\xfe\x00"), ("wrong.js", THEME), ("evil.zip", b"not a zip")):
        r = await client.post("/api/designs", data=form((name, data)))
        assert r.status == 400, (name, r.status)
    # one bad file in a batch: nothing at all is installed
    r = await client.post("/api/designs", data=form(("good.css", THEME), ("Bad.css", THEME)))
    assert r.status == 400 and not (mine / "themes").exists()


async def test_only_admins_install(client, mine):
    await login(client, "guest@pve")
    assert (await (await client.get("/api/me")).json())["admin"] is False
    assert (await client.post("/api/designs", data=form(("neon-night.css", THEME)))).status == 403
    assert (await client.delete("/api/designs/themes/dusk")).status == 403
    assert not (mine / "themes").exists()


def test_kind_detection():
    assert designs.kind_of("a.js", "") == "clocks"
    assert designs.kind_of("a.css", ".bgx[data-k=a]{}") == "backgrounds"
    assert designs.kind_of("a.css", "/*\n @family \"X\", sans-serif\n*/") == "fonts"
    assert designs.kind_of("a.css", "/* @kind widget */ .x{}") == "widgets"
    assert designs.kind_of("a.css", "", folder="theme") == "themes"
    with pytest.raises(designs.DesignError):
        designs.kind_of("a.css", "/* @kind sticker */")


# ---------------- tools for working on designs ----------------
import asyncio  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402


def new_design(tmp, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "new_design.py"), *args, "--to", str(tmp)],
                          capture_output=True, text=True)


@pytest.mark.parametrize("kind,did,folder,ext,marker", [
    ("theme", "neon-night", "themes", "css", 'data-skin="neon-night"'),
    ("background", "my-hills", "backgrounds", "css", 'data-k="my-hills"'),
    ("clock", "big", "clocks", "js", "export function render"),
    ("font", "my-font", "fonts", "css", "@family"),
    ("widget", "host", "widgets", "css", '.w[data-w="host"]'),
])
def test_new_design_is_a_valid_design(tmp_path, monkeypatch, kind, did, folder, ext, marker):
    r = new_design(tmp_path, kind, did, "--name", "Mine")
    assert r.returncode == 0, r.stderr
    text = (tmp_path / folder / f"{did}.{ext}").read_text(encoding="utf-8")
    assert marker in text and f"@kind {kind}" in text
    if kind in ("theme", "background"):
        assert "dusk" not in text.split("*/", 1)[1] and "mountains" not in text.split("*/", 1)[1]
    # it is found as a design of that kind, with its name, and would install as such
    monkeypatch.setattr(config, "USER_DESIGNS_DIR", str(tmp_path))
    m = next(x for x in designs.catalog(folder) if x["id"] == did)
    assert m["source"] == "user" and m["name"]["en"] == "Mine"
    assert designs.kind_of(f"{did}.{ext}", text) == folder


def test_new_design_refuses(tmp_path):
    assert new_design(tmp_path, "theme", "Bad").returncode != 0
    assert new_design(tmp_path, "widget", "nope").returncode != 0
    assert new_design(tmp_path, "theme", "a").returncode == 0
    assert new_design(tmp_path, "theme", "a").returncode != 0          # no silent overwrite
    assert new_design(tmp_path, "theme", "a", "--force").returncode == 0


def test_snapshot_changes(mine):
    before = designs.snapshot()
    write(mine, "themes", "zz.css", "/* @kind theme */")
    after = designs.snapshot()
    assert designs.changes(before, after) == {"changed": [{"kind": "themes", "id": "zz"}], "catalog": True}
    os.utime(mine / "themes" / "zz.css", ns=(1, 1))
    assert designs.changes(after, designs.snapshot()) == {"changed": [{"kind": "themes", "id": "zz"}], "catalog": False}
    write(mine, "themes", "dusk.css", "/* mine */")          # yours over a built-in: same id, new file in use
    c = designs.changes(designs.snapshot(), designs.snapshot())
    assert c == {"changed": [], "catalog": False}


async def test_live_reload_events(client, mine):
    write(mine, "themes", "live.css", "/* @kind theme */ a{}")
    r = await client.get("/api/designs/events")
    assert r.status == 200 and r.headers["Content-Type"].startswith("text/event-stream")
    await asyncio.sleep(0.2)
    os.utime(mine / "themes" / "live.css", ns=(5, 5))
    line = b""
    for _ in range(40):
        line = await asyncio.wait_for(r.content.readline(), 5)
        if line.startswith(b"data:"):
            break
    assert json.loads(line[5:]) == {"changed": [{"kind": "themes", "id": "live"}], "catalog": False}
    r.close()


@pytest.mark.filterwarnings("ignore:Changing state of started")
async def test_live_reload_off_outside_designer_mode(client):
    client.server.app["demo"] = False   # a real host without designer: true
    try:
        assert (await client.get("/api/designs/events")).status == 404
        pub = await (await client.get("/api/public", headers=SEAT)).json()
        assert pub["designer"] is False
    finally:
        client.server.app["demo"] = True


async def test_live_reload_stream_ends_on_shutdown(client):
    """An open live-reload stream must not hold the server up when it stops."""
    r = await client.get("/api/designs/events")
    await asyncio.sleep(0.2)
    client.server.app["stopping"].set()
    rest = await asyncio.wait_for(r.content.read(), 3)   # the server closes the stream: EOF
    assert rest == b""
    client.server.app["stopping"].clear()


# A theme may move things around (DESIGNS.md, "Moving things around"), but only under its own
# [data-skin]: every theme's stylesheet is loaded at once.
@pytest.mark.parametrize("css,bad", [
    ('.A[data-skin="x"],.A [data-skin="x"]{--acc:red}', None),
    ('@media (min-width:901px){.A[data-skin="x"] [data-part="topbar"]{bottom:0}}', None),
    ('.A[data-skin=x] .w[data-w="host"] .ring .fg{stroke:var(--acc)}', None),
    ('@import url("https://fonts.googleapis.com/css2?family=VT323");\n@keyframes k{from{opacity:0}to{opacity:1}}'
     '\n.A[data-skin="x"]{animation:k 1s}', None),
    ('.A[data-skin="x"]{--a:1;&:hover{--a:2}}', None),                       # nested rules sit under their parent
    (":root{--acc:red}", ":root"),
    ('.A[data-skin="dusk"]{--acc:red}', '.A[data-skin="dusk"]'),
    ('.A[data-skin="x"],.top{bottom:0}', ".top"),
    ('@media (min-width:1px){[data-part="topbar"]{bottom:0}}', '[data-part="topbar"]'),
    ('/* [data-skin="x"] */ .top{bottom:0}', ".top"),
    ('.A[data-skin="x2"]{a:b}', '.A[data-skin="x2"]'),
    ('.A[data-skin^="x"]{a:b}', '.A[data-skin^="x"]'),                       # a prefix would reach other themes
])
def test_theme_rules_stay_under_their_own_skin(css, bad):
    assert designs.unscoped(css, "x") == bad


def test_builtin_themes_are_scoped():
    folder = os.path.join(ROOT, "designs", "themes")
    for f in os.listdir(folder):
        with open(os.path.join(folder, f), encoding="utf-8") as fh:
            assert designs.unscoped(fh.read(), f[:-4]) is None, f


async def test_a_theme_that_reaches_other_themes_is_refused(client, mine):
    await login(client)
    leaky = b"/*\n * @kind theme\n */\n.A[data-skin=\"tmux\"]{--acc:#0f0}\n.top{bottom:0}\n"
    r = await client.post("/api/designs", data=form(("tmux.css", leaky)))
    assert r.status == 400 and "data-skin" in (await r.json())["error"]
    assert not (mine / "themes").exists()
    ok = leaky.replace(b".top{", b".A[data-skin=\"tmux\"] [data-part=\"topbar\"]{")
    assert (await client.post("/api/designs", data=form(("tmux.css", ok)))).status == 200
