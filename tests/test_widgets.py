"""Your own widgets: /etc/pve-homelab/widgets/<id>/widget.js next to the built-in ones."""

import asyncio
import io
import json
import os
import zipfile

import pytest
from aiohttp import FormData

from pvehomelab import config, userwidgets

from conftest import login

SEAT = {"X-Seat": "igpu"}
JS = b"export default { zones: ['side'], render: (_d, { t }) => `<h4>${t('title')}</h4>` };\n"
CSS = b".A .w[data-w=\"mine\"]{outline:1px solid red}\n"
EN = '{"title": "Mine", "n": {"one": "{n} thing", "other": "{n} things"}}'.encode()
UK = '{"title": "Мій", "n": {"one": "{n} річ", "few": "{n} речі", "many": "{n} речей", "other": "{n} речі"}}'.encode()


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Empty folders for your widgets and your designs."""
    monkeypatch.setattr(config, "USER_WIDGETS_DIR", str(tmp_path / "widgets"))
    monkeypatch.setattr(config, "USER_DESIGNS_DIR", str(tmp_path / "designs"))
    return tmp_path


def form(*files):
    f = FormData()
    for name, data in files:
        f.add_field("file", data, filename=name, content_type="application/octet-stream")
    return f


def put(root, wid, text=JS):
    os.makedirs(root / "widgets" / wid, exist_ok=True)
    (root / "widgets" / wid / "widget.js").write_bytes(text)


def zipped(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def test_lists_builtin_and_yours(folders):
    put(folders, "mine")
    put(folders, "host", b"export default {}")   # a built-in id: never yours
    put(folders, "Bad Name")
    ids = userwidgets.all_ids()
    assert {"host", "note", "mine"} <= set(ids) and "Bad Name" not in ids
    assert userwidgets.user_ids() == {"mine"}
    assert userwidgets.path_of("host") == os.path.join(config.WEB_DIR, "widgets", "host", "widget.js")
    assert userwidgets.path_of("mine") == str(folders / "widgets" / "mine" / "widget.js")
    assert userwidgets.path_of("../etc") is None and userwidgets.path_of("nope") is None


async def test_served_and_listed(client, folders):
    put(folders, "mine")
    r = await client.get("/widgets/mine/widget.js")
    assert r.status == 200 and "javascript" in r.headers["Content-Type"]
    assert r.headers["Cache-Control"] == "no-cache"
    assert await r.read() == JS
    assert (await client.get("/widgets/host/widget.js")).status == 200        # built-in still served
    for url in ("/widgets/nope/widget.js", "/widgets/UP/widget.js", "/widgets/..%2Fx/widget.js"):
        assert (await client.get(url)).status == 404, url
    pub = await (await client.get("/api/public", headers=SEAT)).json()
    assert "mine" in pub["widgets"] and "host" in pub["widgets"]


async def test_admin_installs_and_removes(client, folders):
    await login(client)
    r = await client.post("/api/widgets", data=form(("mine.js", JS), ("mine.css", CSS)))
    assert r.status == 200, await r.text()
    assert (await r.json())["installed"] == [{"id": "mine", "look": True, "languages": []}]
    assert (folders / "widgets" / "mine" / "widget.js").read_bytes() == JS
    assert (folders / "designs" / "widgets" / "mine.css").read_bytes() == CSS   # its look is a design
    assert await (await client.get("/widgets/mine/widget.js")).read() == JS
    assert "outline" in await (await client.get("/widgets/mine/widget.css")).text()
    pub = await (await client.get("/api/public", headers=SEAT)).json()
    assert "mine" in pub["widgets"] and "mine" in pub["widget_styles"]
    assert (await (await client.get("/api/widgets")).json())["mine"] == [{"id": "mine", "look": True, "languages": []}]

    assert (await client.delete("/api/widgets/mine")).status == 200
    assert not (folders / "widgets" / "mine").exists()
    assert (await client.get("/widgets/mine/widget.js")).status == 404
    assert (await client.delete("/api/widgets/mine")).status == 404
    assert (await client.delete("/api/widgets/host")).status == 404   # built-in ones can't be removed


async def test_zip_with_several_widgets(client, folders):
    data = zipped([("pack/clockish/widget.js", JS), ("pack/clockish/widget.css", CSS),
                   ("pack/plain.js", JS), ("pack/README.md", "hi"), ("__MACOSX/._x", "x")])
    await login(client)
    r = await client.post("/api/widgets", data=form(("pack.zip", data)))
    assert r.status == 200, await r.text()
    assert (await r.json())["installed"] == [{"id": "clockish", "look": True, "languages": []},
                                             {"id": "plain", "look": False, "languages": []}]


def test_zip_layouts():
    # a folder laid out like /etc/pve-homelab, other designs in it are left alone
    found = userwidgets.unpack([("mine.zip", zipped([("widgets/up/widget.js", JS), ("designs/widgets/up.css", CSS),
                                                     ("designs/themes/dusk.css", "x")]))])
    assert set(found) == {"up"} and found["up"]["css"] == CSS.decode()
    # widget.js at the top of a zip: named like the zip
    found = userwidgets.unpack([("uptime.zip", zipped([("widget.js", JS), ("widget.css", CSS)]))])
    assert set(found) == {"uptime"} and found["uptime"]["css"]
    with pytest.raises(userwidgets.WidgetError, match="name it"):
        userwidgets.unpack([("widget.js", JS)])


async def test_reinstall_replaces(client, folders):
    await login(client)
    assert (await client.post("/api/widgets", data=form(("mine.js", JS)))).status == 200
    v2 = JS.replace(b"</h4>", b" v2</h4>")
    assert (await client.post("/api/widgets", data=form(("mine.js", v2)))).status == 200
    assert b"v2" in await (await client.get("/widgets/mine/widget.js")).read()


async def test_bad_uploads_refused_and_nothing_written(client, folders):
    await login(client)
    for files in ([("host.js", JS)],                      # a built-in id
                  [("Bad Name.js", JS)],
                  [("mine.js", b"console.log(1)")],       # not a widget module
                  [("mine.js", b"\xff\xfe\x00")],
                  [("mine.js", b"export default {}" + b" " * userwidgets.MAX_JS)],
                  [("mine.css", CSS)],                     # a look without its widget
                  [("mine.exe", b"MZ")],
                  [("mine.zip", b"not a zip")],
                  [("x.zip", zipped([("README.md", "nothing here")]))],
                  [("ok.js", JS), ("host.js", JS)]):       # one bad file: nothing at all
        r = await client.post("/api/widgets", data=form(*files))
        assert r.status == 400, (files[0][0], r.status, await r.text())
    assert not (folders / "widgets").exists() and not (folders / "designs").exists()


async def test_only_admins_install(client, folders):
    put(folders, "mine")
    await login(client, "guest@pve")
    assert (await client.post("/api/widgets", data=form(("other.js", JS)))).status == 403
    assert (await client.delete("/api/widgets/mine")).status == 403
    assert (folders / "widgets" / "mine").exists() and not (folders / "widgets" / "other").exists()
    assert (await client.get("/widgets/mine/widget.js")).status == 200   # everyone can run it, though


async def test_live_reload_reloads_on_widget_change(client, folders):
    put(folders, "mine")
    r = await client.get("/api/designs/events")
    await asyncio.sleep(0.2)
    os.utime(folders / "widgets" / "mine" / "widget.js", ns=(5, 5))
    line = b""
    for _ in range(40):
        line = await asyncio.wait_for(r.content.readline(), 5)
        if line.startswith(b"data:"):
            break
    assert json.loads(line[5:]) == {"changed": [], "catalog": True}
    r.close()


# ---------------- strings apart from the code ----------------
def test_builtin_widgets_keep_strings_in_files():
    t = userwidgets.translations()
    for wid in userwidgets.builtin_ids():
        assert t[wid]["en"]["title"] and t[wid]["uk"]["title"], wid
    assert t["note"]["uk"]["title"] == "Нотатка"


async def test_strings_served_yours_over_builtin(client, folders):
    put(folders, "mine")
    os.makedirs(folders / "widgets" / "mine" / "i18n")
    (folders / "widgets" / "mine" / "i18n" / "en.json").write_bytes(EN)
    os.makedirs(folders / "widgets" / "note" / "i18n")           # a language of your own for a built-in widget
    (folders / "widgets" / "note" / "i18n" / "pl.json").write_text('{"title": "Notatka"}', encoding="utf-8")
    (folders / "widgets" / "note" / "i18n" / "xx.json").write_text("not json", encoding="utf-8")  # skipped
    r = await client.get("/widgets/i18n.json")
    assert r.status == 200 and r.headers["Cache-Control"] == "no-cache"
    data = await r.json()
    assert data["mine"]["en"]["n"]["other"] == "{n} things"
    assert data["note"]["pl"]["title"] == "Notatka" and data["note"]["uk"]["title"] == "Нотатка"
    assert "xx" not in data["note"]


async def test_install_with_strings(client, folders):
    await login(client)
    r = await client.post("/api/widgets", data=form(("mine.js", JS), ("mine.en.json", EN), ("mine.uk.json", UK)))
    assert r.status == 200, await r.text()
    assert (await r.json())["installed"] == [{"id": "mine", "look": False, "languages": ["en", "uk"]}]
    assert (folders / "widgets" / "mine" / "i18n" / "uk.json").read_bytes() == UK
    assert (await (await client.get("/widgets/i18n.json")).json())["mine"]["uk"]["title"] == "Мій"
    # a new version of the code alone keeps the strings; strings sent replace their language only
    assert (await client.post("/api/widgets", data=form(("mine.js", JS), ("mine.en.json", b'{"title": "Mine 2"}')))).status == 200
    assert (folders / "widgets" / "mine" / "i18n" / "uk.json").exists()
    assert json.loads((folders / "widgets" / "mine" / "i18n" / "en.json").read_text())["title"] == "Mine 2"
    assert (await (await client.get("/api/widgets")).json())["mine"][0]["languages"] == ["en", "uk"]


def test_zip_with_strings():
    found = userwidgets.unpack([("p.zip", zipped([
        ("p/up/widget.js", JS), ("p/up/i18n/en.json", EN), ("p/up/i18n/uk.json", UK),   # a widget's folder
        ("widgets/down/widget.js", JS), ("widgets/down/i18n/en.json", EN),           # laid out like /etc/pve-homelab
        ("side.js", JS), ("side.uk.json", UK),                                        # loose
        ("package.json", "{}"), ("other/i18n/en.json", EN)])),                       # not a widget's: left out
        ("top.zip", zipped([("widget.js", JS), ("i18n/en.json", EN)]))])            # widget.js on top
    assert {w: sorted(p["i18n"]) for w, p in found.items()} == {"up": ["en", "uk"], "down": ["en"], "side": ["uk"], "top": ["en"]}


async def test_bad_strings_refused(client, folders):
    await login(client)
    for files in ([("mine.js", JS), ("mine.en.json", b"not json")],
                  [("mine.js", JS), ("mine.en.json", b'["a list"]')],
                  [("mine.js", JS), ("mine.en.json", b'{"title": 5}')],
                  [("mine.js", JS), ("mine.EN!.json", EN)],
                  [("mine.js", JS), ("mine.json", EN)],                  # no language in the name
                  [("mine.uk.json", UK)],                                # strings without the widget
                  [("mine.js", JS), ("mine.en.json", b'{"t": "' + b"x" * userwidgets.MAX_I18N + b'"}')]):
        r = await client.post("/api/widgets", data=form(*files))
        assert r.status == 400, (files[-1][0], r.status, await r.text())
    assert not (folders / "widgets").exists()


async def test_live_reload_on_strings_change(client, folders):
    put(folders, "mine")
    os.makedirs(folders / "widgets" / "mine" / "i18n")
    (folders / "widgets" / "mine" / "i18n" / "en.json").write_bytes(EN)
    r = await client.get("/api/designs/events")
    await asyncio.sleep(0.2)
    os.utime(folders / "widgets" / "mine" / "i18n" / "en.json", ns=(5, 5))
    line = b""
    for _ in range(40):
        line = await asyncio.wait_for(r.content.readline(), 5)
        if line.startswith(b"data:"):
            break
    assert json.loads(line[5:]) == {"changed": [], "catalog": True}
    r.close()


def test_new_widget_scaffold(tmp_path):
    import subprocess
    import sys
    from conftest import ROOT
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "new_widget.py"), "my-thing", "--to", str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    js = (tmp_path / "widgets" / "my-thing" / "widget.js").read_bytes()
    css = (tmp_path / "designs" / "widgets" / "my-thing.css").read_bytes()
    en = json.loads((tmp_path / "widgets" / "my-thing" / "i18n" / "en.json").read_text(encoding="utf-8"))
    uk = json.loads((tmp_path / "widgets" / "my-thing" / "i18n" / "uk.json").read_text(encoding="utf-8"))
    assert en["title"] == "My thing" and set(en) == set(uk)
    assert b"i18n:" not in js                    # strings live apart from the code
    found = userwidgets.unpack([("my-thing.js", js), ("my-thing.css", css)])
    assert set(found) == {"my-thing"} and found["my-thing"]["css"]
    assert b'data-w="my-thing"' in css
    again = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "new_widget.py"), "my-thing", "--to", str(tmp_path)],
                           capture_output=True, text=True)
    assert again.returncode != 0   # won't overwrite without --force
    taken = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "new_widget.py"), "host", "--to", str(tmp_path)],
                           capture_output=True, text=True)
    assert taken.returncode != 0   # a built-in id
