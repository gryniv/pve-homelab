"""The documentation keeps up with the code: every option is in the example config, every built-in
widget is in both READMEs, every design the docs name ships, both backend languages say everything."""

import glob
import json
import os
import re

import pytest

from pvehomelab import config, i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_every_option_is_in_the_example_config():
    example = set(re.findall(r"^([a-z_]+):", read("etc", "config.example.yaml"), re.M))
    assert set(config.DEFAULTS) - example == set()


WIDGETS = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ROOT, "web", "widgets", "*", "widget.js")))


@pytest.mark.parametrize("readme,lang", [("README.md", "en"), ("README.uk.md", "uk")])
def test_every_widget_is_in_the_readme(readme, lang):
    rows = {m.strip() for m in re.findall(r"^\s*\|([^|]+)\|", read(readme), re.M)}
    missing = [w for w in WIDGETS
               if json.loads(read("web", "widgets", w, "i18n", f"{lang}.json"))["title"] not in rows]
    assert missing == []


@pytest.mark.parametrize("doc", ["DESIGNS.md", "DESIGNS.uk.md"])
def test_designs_named_in_the_examples_ship(doc):
    blocks = "\n".join(re.findall(r"```[a-z]*\n(.*?)```", read(doc), re.S))
    for kind, folder, ext in (("background", "backgrounds", "css"), ("clock", "clocks", "js")):
        for name in re.findall(rf"@{kind}\s+([a-z0-9-]+)", blocks):
            assert os.path.exists(os.path.join(ROOT, "designs", folder, f"{name}.{ext}")), f"{doc}: @{kind} {name}"


def test_backend_messages_in_every_language():
    en = set(i18n.MESSAGES["en"])
    for lang, msgs in i18n.MESSAGES.items():
        assert set(msgs) == en, lang
