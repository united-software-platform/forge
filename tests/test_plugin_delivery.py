"""Поставка плагином: манифест, файл зависимостей, запись маркетплейса."""

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin" / "forge"
PIN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,-]+\])?)==(?P<version>[0-9][^\s]*)$")


def _pyproject():
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _requirements():
    lines = (PLUGIN / "src" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def test_манифест_несёт_версию_пакета():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "forge"
    assert manifest["description"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["version"] == _pyproject()["project"]["version"]


def test_зависимости_поставки_только_точные_пины():
    pins = [line for line in _requirements() if not line.startswith("#")]

    assert pins
    for line in pins:
        assert PIN.match(line), f"не пин ==: {line}"


def test_пины_поставки_совпадают_с_зависимостями_проекта():
    pins = sorted(line for line in _requirements() if not line.startswith("#"))

    assert sorted(_pyproject()["project"]["dependencies"]) == pins


def test_маркетплейс_публикует_плагин_относительным_путём():
    marketplace = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "forge")

    assert entry["source"] == "./plugin/forge"
    assert (REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_репозиторий_подключает_плагин_локальным_маркетплейсом():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    name = marketplace["name"]

    assert settings["extraKnownMarketplaces"][name]["source"] == {
        "source": "directory",
        "path": ".",
    }
    assert settings["enabledPlugins"][f"forge@{name}"] is True


def test_механизм_лежит_только_под_корнем_плагина():
    assert not (REPO / "tools" / "forge_model").exists()
    assert (PLUGIN / "src" / "forge_model" / "cli.py").is_file()
    assert (PLUGIN / "bin" / "forge").stat().st_mode & 0o111
