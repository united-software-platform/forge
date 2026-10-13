"""Командная строка: выпуск, повторный выпуск, ошибки процесса, неизменяемость файлов."""

import shutil

import pytest
import yaml
from forge_model import registry
from forge_model.cli import main


@pytest.fixture
def workspace(model_root, tmp_path):
    """Рабочая копия проекта: модель, каталог выпусков, каталог миграций."""
    model = tmp_path / "model" / "forge.reqs.v1"
    shutil.copytree(model_root, model)
    return {
        "root": tmp_path,
        "model": model,
        "releases": tmp_path / "model" / "releases",
        "changelog": tmp_path / "changelog",
    }


def _run(workspace, command, *extra):
    return main(
        [
            command,
            "--model",
            str(workspace["model"]),
            "--releases",
            str(workspace["releases"]),
            "--changelog",
            str(workspace["changelog"]),
            *extra,
        ]
    )


def _bump(workspace, version, mutate=None):
    if mutate:
        path = workspace["model"] / "types" / "br.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        mutate(raw)
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    manifest = workspace["model"] / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_сборка_печатает_версию_и_хеш(workspace, capsys):
    assert _run(workspace, "build") == 0
    out = capsys.readouterr().out
    assert "forge.reqs 1.2.0" in out and "sha256:" in out


def test_начальный_выпуск_создаёт_свёртку_и_дескриптор(workspace):
    assert _run(workspace, "gen", "--baseline") == 0

    assert (workspace["releases"] / "1.2.0.json").exists()
    assert (workspace["changelog"] / "master.yaml").exists()
    assert registry.load(workspace["changelog"])[0]["version"] == "1.2.0"


def test_повторный_выпуск_ничего_не_создаёт(workspace, capsys):
    _run(workspace, "gen", "--baseline")
    before = sorted(p.name for p in workspace["changelog"].rglob("*.sql"))

    assert _run(workspace, "gen") == 0
    assert "выпускать нечего" in capsys.readouterr().out
    assert sorted(p.name for p in workspace["changelog"].rglob("*.sql")) == before


def test_выпуск_изменения_печатает_дельту(workspace, capsys):
    _run(workspace, "gen", "--baseline")
    _bump(
        workspace,
        "1.3.0",
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
    )

    assert _run(workspace, "gen") == 0
    out = capsys.readouterr().out
    assert "1.2.0 -> 1.3.0" in out
    assert "добавлено поле owner" in out
    assert (workspace["releases"] / "1.3.0.json").exists()


def test_удаление_поля_выпускается_с_предупреждением(workspace, capsys):
    _run(workspace, "gen", "--baseline")
    _bump(workspace, "1.3.0", lambda raw: raw["fields"].pop(3))

    assert _run(workspace, "gen") == 0
    out = capsys.readouterr().out
    assert "ВНИМАНИЕ" in out
    assert "данные колонки origin будут удалены" in out
    assert "занято навсегда: BR.4 (origin)" in out


def test_правка_без_повышения_версии_останавливает(workspace, capsys):
    _run(workspace, "gen", "--baseline")
    _bump(
        workspace,
        "1.2.0",
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
    )

    assert _run(workspace, "gen") == 1
    assert "повысьте средний разряд" in capsys.readouterr().err


def test_изменение_выпущенного_файла_обнаруживается(workspace):
    _run(workspace, "gen", "--baseline")
    target = next(workspace["changelog"].rglob("*.sql"))
    target.write_text(target.read_text(encoding="utf-8") + "\n-- правка руками\n", encoding="utf-8")

    problems = registry.verify_immutability(workspace["changelog"])
    assert len(problems) == 1
    assert "изменён после выпуска" in problems[0]


def test_удаление_выпущенного_файла_обнаруживается(workspace):
    _run(workspace, "gen", "--baseline")
    next(workspace["changelog"].rglob("*.sql")).unlink()

    assert "удалён" in registry.verify_immutability(workspace["changelog"])[0]


def test_запросы_проверок_печатаются(workspace, capsys):
    assert _run(workspace, "checks") == 0
    out = capsys.readouterr().out
    assert "realizes.from_cardinality" in out
    assert "links.suspect" in out


@pytest.fixture
def project(workspace, monkeypatch):
    """Рабочая копия как проект git: корень по маркеру `.git`, переменные входа сброшены."""
    (workspace["root"] / ".git").mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    for variable in (
        "FORGE_MODEL_DIR",
        "FORGE_RELEASES_DIR",
        "FORGE_CHANGELOG_DIR",
        "FORGE_RUNS_DIR",
    ):
        monkeypatch.delenv(variable, raising=False)
    return workspace


def test_сборка_из_подкаталога_читает_модель_корня(project, monkeypatch, capsys):
    monkeypatch.chdir(project["root"])
    assert main(["build"]) == 0
    from_root = capsys.readouterr().out

    nested = project["root"] / "docs" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert main(["build"]) == 0
    assert capsys.readouterr().out == from_root


def test_корень_проекта_из_переменной_claude(project, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path_factory.mktemp("вне-проекта"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project["root"]))

    assert main(["build"]) == 0


def test_без_корня_проекта_код_два(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("FORGE_MODEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert main(["build"]) == 2
    assert "корень проекта не найден" in capsys.readouterr().err


def test_переменная_переносит_каталог_миграций(project, monkeypatch):
    monkeypatch.chdir(project["root"])
    monkeypatch.setenv("FORGE_CHANGELOG_DIR", "migrations")

    assert main(["gen", "--baseline"]) == 0
    assert (project["root"] / "migrations" / "master.yaml").exists()
    assert not project["changelog"].exists()


def test_ключ_перекрывает_переменную(project, monkeypatch):
    monkeypatch.chdir(project["root"])
    monkeypatch.setenv("FORGE_MODEL_DIR", str(project["root"] / "нет-такой-модели"))

    assert main(["build"]) == 2
    assert main(["build", "--model", str(project["model"])]) == 0


def test_недоступное_хранилище_код_два(workspace, capsys):
    code = main(
        [
            "verify",
            "--model",
            str(workspace["model"]),
            "--changelog",
            str(workspace["changelog"]),
            "--dsn",
            "postgresql://forge@127.0.0.1:1/forge?connect_timeout=2",
        ]
    )

    assert code == 2
    assert "хранилище недоступно" in capsys.readouterr().err


def test_первый_прогон_цикла_рекомендует_gitignore(project, monkeypatch, capsys):
    monkeypatch.chdir(project["root"])
    ignore = project["root"] / ".gitignore"
    ignore.write_text(".venv/\n", encoding="utf-8")
    scenario = project["root"] / "scenario.yaml"
    scenario.write_text("intent: INT-001\npositions: [поле FR.code]\n", encoding="utf-8")

    assert main(["intent", "run", "--scenario", str(scenario)]) == 0
    assert "добавьте в .gitignore строку model/intents/runs/" in capsys.readouterr().err
    assert ignore.read_text(encoding="utf-8") == ".venv/\n"

    assert main(["intent", "run", "--scenario", str(scenario)]) == 0
    assert "РЕКОМЕНДАЦИЯ" not in capsys.readouterr().err


def test_каталог_в_gitignore_не_рекомендуется(project, monkeypatch, capsys):
    monkeypatch.chdir(project["root"])
    (project["root"] / ".gitignore").write_text("/model/intents/runs/\n", encoding="utf-8")
    scenario = project["root"] / "scenario.yaml"
    scenario.write_text("intent: INT-001\npositions: [поле FR.code]\n", encoding="utf-8")

    assert main(["intent", "run", "--scenario", str(scenario)]) == 0
    assert "РЕКОМЕНДАЦИЯ" not in capsys.readouterr().err
