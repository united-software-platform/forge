"""Окружение входа: сборка, повторное использование по метке, пересборка, исчерпание способов.

Сборка проверяется без сети: `uv` и `python3` подменяются заглушками в изолированном PATH,
а заглушка `uv` записывает каждый вызов в журнал. Настоящую сборку проверяют тесты входа.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin" / "forge"
TOOLS = ("grep", "mkdir", "rm", "mv", "ln")

UV_STUB = """#!/bin/sh
printf '%s\\n' "$*" >>"$UV_LOG"
case $1 in
    venv) for last; do :; done; mkdir -p "$last/bin" && ln -s "$REAL_PYTHON" "$last/bin/python" ;;
    pip) exit 0 ;;
esac
"""

PYTHON_WITHOUT_VENV = """#!/bin/sh
if [ "$1" = -m ] && [ "$2" = venv ]; then exit 1; fi
exec "$REAL_PYTHON" "$@"
"""


@pytest.fixture
def sandbox(tmp_path):
    """Корень поставки с файлом зависимостей и изолированный PATH."""
    root = tmp_path / "plugin"
    (root / "lib").mkdir(parents=True)
    (root / "src").mkdir()
    shutil.copy(PLUGIN / "lib" / "python-env.sh", root / "lib")
    shutil.copy(PLUGIN / "src" / "requirements.txt", root / "src")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        (bin_dir / tool).symlink_to(shutil.which(tool))
    (bin_dir / "python3").symlink_to(sys.executable)

    return {
        "root": root,
        "bin": bin_dir,
        "data": tmp_path / "data",
        "log": tmp_path / "uv.log",
    }


def _stub(sandbox, name, body):
    path = sandbox["bin"] / name
    if path.is_symlink():
        path.unlink()
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _prepare(sandbox):
    script = '. "$1/lib/python-env.sh"; prepare_python_env "$1"; rc=$?; echo "PY=${PY:-}"; exit $rc'
    env = {
        "PATH": str(sandbox["bin"]),
        "HOME": str(sandbox["data"].parent),
        "CLAUDE_PLUGIN_DATA": str(sandbox["data"]),
        "UV_LOG": str(sandbox["log"]),
        "REAL_PYTHON": sys.executable,
    }
    return subprocess.run(
        ["/bin/sh", "-c", script, "prepare", str(sandbox["root"])],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _builds(sandbox):
    if not sandbox["log"].exists():
        return 0
    return sandbox["log"].read_text(encoding="utf-8").count("venv")


def test_окружение_собирается_в_каталоге_данных(sandbox):
    _stub(sandbox, "uv", UV_STUB)

    result = _prepare(sandbox)

    assert result.returncode == 0, result.stderr
    env = sandbox["data"] / "env"
    assert f"PY={env}/bin/python" in result.stdout
    mark = (env / ".env-mark").read_text(encoding="utf-8")
    assert "method=uv" in mark
    assert "python=" in mark and "requirements=" in mark
    assert sorted(p.name for p in sandbox["root"].rglob("*")) == [
        "lib",
        "python-env.sh",
        "requirements.txt",
        "src",
    ]


def test_совпавшая_метка_не_пересобирает(sandbox):
    _stub(sandbox, "uv", UV_STUB)
    _prepare(sandbox)

    assert _prepare(sandbox).returncode == 0
    assert _builds(sandbox) == 1


def test_смена_пина_пересобирает(sandbox):
    _stub(sandbox, "uv", UV_STUB)
    _prepare(sandbox)
    requirements = sandbox["root"] / "src" / "requirements.txt"
    requirements.write_text(
        requirements.read_text(encoding="utf-8").replace("6.0.3", "6.0.2"), encoding="utf-8"
    )

    assert _prepare(sandbox).returncode == 0
    assert _builds(sandbox) == 2


def test_без_пинов_окружение_не_собирается(sandbox):
    _stub(sandbox, "uv", UV_STUB)
    (sandbox["root"] / "src" / "requirements.txt").write_text("# пусто\n", encoding="utf-8")

    result = _prepare(sandbox)

    assert result.returncode == 0
    assert "PY=python3" in result.stdout
    assert not sandbox["data"].exists()


def test_без_uv_собирается_модулем_venv(sandbox):
    result = _prepare(sandbox)

    if result.returncode != 0 and "pip" in result.stderr:
        pytest.skip("pip не может поставить зависимости без сети")
    assert result.returncode == 0, result.stderr
    assert "method=venv" in (sandbox["data"] / "env" / ".env-mark").read_text(encoding="utf-8")


def test_без_обоих_способов_код_два(sandbox):
    (sandbox["bin"] / "python3").unlink()
    _stub(sandbox, "python3", PYTHON_WITHOUT_VENV)

    result = _prepare(sandbox)

    assert result.returncode == 2
    assert "испробованы способы: uv venv" in result.stderr
    assert not (sandbox["data"] / "env").exists()
    assert not any(name.startswith("env.build") for name in os.listdir(sandbox["data"]))
