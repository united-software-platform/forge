"""Вход `bin/forge`: справка подкоманд, вызов вне проекта, отсутствие записи в корень плагина.

Тесты вызывают настоящий вход отдельным процессом. Окружение зависимостей собирается один раз
за прогон в каталоге данных, который задаёт тест, — не в пользовательском кеше.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin" / "forge"
ENTRY = PLUGIN / "bin" / "forge"
SUBCOMMANDS = (
    ["build"],
    ["diff"],
    ["gen"],
    ["checks"],
    ["verify"],
    ["intent", "run"],
    ["norms"],
    ["sample"],
)


@pytest.fixture(scope="session")
def plugin_data(tmp_path_factory):
    return tmp_path_factory.mktemp("plugin-data")


@pytest.fixture
def forge(plugin_data):
    def call(*args, cwd, **env):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("FORGE_", "CLAUDE_PROJECT_DIR", "PYTHON", "VIRTUAL_ENV"))
        }
        environment.update(CLAUDE_PLUGIN_DATA=str(plugin_data), **env)
        return subprocess.run(
            [str(ENTRY), *args],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    return call


@pytest.fixture
def project(model_root, tmp_path):
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    shutil.copytree(model_root, root / "model" / "forge.reqs.v1")
    (root / "scenario.yaml").write_text(
        "intent: INT-001\npositions: [поле FR.code]\n", encoding="utf-8"
    )
    return root


def _snapshot(root: Path):
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
    }


def test_справка_входа(forge, tmp_path):
    result = forge("--help", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    for name in ("build", "diff", "gen", "checks", "verify", "intent", "norms", "sample"):
        assert name in result.stdout


@pytest.mark.parametrize("command", SUBCOMMANDS, ids=" ".join)
def test_справка_подкоманды(forge, tmp_path, command):
    result = forge(*command, "--help", cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_вход_вне_проекта_находит_поставку(forge, tmp_path):
    outside = tmp_path / "вне-проекта"
    outside.mkdir()

    result = forge("norms", "--rule", "MDL-001", cwd=outside)

    assert result.returncode == 0, result.stderr
    assert "**[MDL-001]**" in result.stdout


def test_вход_через_символическую_ссылку(plugin_data, tmp_path):
    link = tmp_path / "bin" / "forge"
    link.parent.mkdir()
    link.symlink_to(ENTRY)

    result = subprocess.run(
        [str(link), "sample"],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PLUGIN_DATA": str(plugin_data)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "==> model/forge.reqs.v1/_manifest.yaml <==" in result.stdout


def test_неизвестный_ключ_код_два(forge, project):
    assert forge("build", "--нет-такого", cwd=project).returncode == 2


def test_вход_не_пишет_в_корень_плагина(forge, project):
    forge("--help", cwd=project)
    before = _snapshot(PLUGIN)

    nested = project / "docs"
    nested.mkdir()
    codes = [
        forge("build", cwd=nested).returncode,
        forge("diff", cwd=nested).returncode,
        forge("gen", "--baseline", cwd=nested).returncode,
        forge("checks", cwd=nested).returncode,
        forge("verify", "--dsn", "postgresql://forge@127.0.0.1:1/forge", cwd=nested).returncode,
        forge("intent", "run", "--scenario", str(project / "scenario.yaml"), cwd=nested).returncode,
        forge("norms", cwd=nested).returncode,
        forge("sample", cwd=nested).returncode,
    ]

    assert codes == [0, 0, 0, 0, 2, 0, 0, 0]
    assert (project / "changelog" / "master.yaml").exists()
    assert _snapshot(PLUGIN) == before
