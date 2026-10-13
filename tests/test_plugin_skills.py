"""Навыки плагина: единая форма, нормы кодом и вызовом, стоп-знак перед выпуском."""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SKILLS = sorted((REPO / "plugin" / "forge" / "skills").glob("*/SKILL.md"))
RULES = REPO / "plugin" / "forge" / "share" / "rules" / "model-rules.md"


def _split(path):
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


def test_навыки_на_месте():
    assert [path.parent.name for path in SKILLS] == ["model-change", "model-release"]


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_фронтматтер_навыка(path):
    front, _ = _split(path)

    assert front["name"] == path.parent.name
    assert front["description"]
    assert "Bash(forge:*)" in [tool.strip() for tool in front["allowed-tools"].split(",")]


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_тело_навыка_имеет_единую_форму(path):
    _, body = _split(path)

    for heading in ("## Границы", "## Шаги", "## Исходы", "## Версионирование"):
        assert heading in body


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_нормы_названы_кодом_и_вызовом_без_пересказа(path):
    _, body = _split(path)
    rules = RULES.read_text(encoding="utf-8")

    flat = " ".join(body.split())
    codes = set(re.findall(r"MDL-\d{3}", body))
    assert codes
    for code in codes:
        assert f"`{code}` (`forge norms --rule {code}`)" in flat, code
        paragraph = re.search(rf"^\*\*\[{code}\]\*\* (.+)$", rules, re.MULTILINE)
        assert paragraph, code
        assert paragraph.group(1) not in body
    assert "model-rules.md" not in body
    assert "share/rules" not in body


def test_выпуск_не_описан_в_навыке_приёмки():
    _, body = _split(SKILLS[0])

    assert "forge:model-release" in body
    assert "forge gen" not in body


def test_стоп_знак_перед_выпуском():
    _, body = _split(SKILLS[1])
    steps = body.split("## Шаги")[1].split("## Исходы")[0]

    confirm = steps.index("подтверждение владельца")
    assert confirm < steps.index("Выполнить `forge gen`")
    assert "`forge gen` не вызывается" in steps


def test_шаги_выпуска_не_перечислены_в_документах():
    for path in [REPO / "README.md", *sorted((REPO / "docs").glob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        assert "forge gen" not in text, path
