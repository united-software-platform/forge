"""Нормы модели, глоссарий и образец как данные поставки: выдача через вход."""

import re
from pathlib import Path

from forge_model import delivery
from forge_model.cli import main

RULE = re.compile(r"^\*\*\[(MDL-\d{3})\]\*\*", re.MULTILINE)


def _rules_text():
    return (delivery.PLUGIN_ROOT / delivery.RULES).read_text(encoding="utf-8")


def _unpack(text, root: Path):
    """Разложить вывод `forge sample` по путям разделителей."""
    current = None
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r"==> (.+) <==\n", line)
        if match:
            current = root / match.group(1)
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_text("", encoding="utf-8")
        elif current is not None:
            with current.open("a", encoding="utf-8") as handle:
                handle.write(line)


def test_коды_правил_уникальны_и_есть_в_таблице():
    text = _rules_text()
    codes = RULE.findall(text)

    assert codes
    assert len(codes) == len(set(codes))
    table = set(re.findall(r"^\| (MDL-\d{3}) \|", text, re.MULTILINE))
    assert table == set(codes)


def test_выдача_всех_норм_и_глоссария(capsys):
    assert main(["norms"]) == 0
    out = capsys.readouterr().out

    for code in RULE.findall(_rules_text()):
        assert f"**[{code}]**" in out
    assert "# Глоссарий модели forge" in out


def test_выдача_раздела_правила(capsys):
    assert main(["norms", "--rule", "MDL-009"]) == 0
    out = capsys.readouterr().out

    assert out.startswith("### Поле\n")
    assert "**[MDL-009]**" in out and "**[MDL-012]**" in out
    assert "**[MDL-013]**" not in out


def test_неизвестное_правило_код_два(capsys):
    assert main(["norms", "--rule", "MDL-999"]) == 2
    assert "MDL-999" in capsys.readouterr().err


def test_понятия_норм_раскрыты_в_глоссарии():
    glossary = (delivery.PLUGIN_ROOT / delivery.GLOSSARY).read_text(encoding="utf-8")
    used = set(re.findall(r"\(([A-Z][A-Za-z ]+)\)", _rules_text()))

    assert used
    for term in used:
        assert f"({term})" in glossary, term


def test_образец_собирается(tmp_path, capsys, monkeypatch):
    assert main(["sample"]) == 0
    _unpack(capsys.readouterr().out, tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("FORGE_MODEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert main(["build"]) == 0
    assert "forge.reqs 1.0.0" in capsys.readouterr().out


def test_образец_называет_нормы_кодом_и_вызовом():
    root = delivery.PLUGIN_ROOT / delivery.SAMPLE
    for path in root.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for code in re.findall(r"MDL-\d{3}", text):
            assert f"{code} (forge norms --rule {code})" in text, path
        assert "model-rules.md" not in text
