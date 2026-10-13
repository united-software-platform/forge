"""Эталон выпуска: дескрипторы, миграции, порядок применения, реестр и вывод подкоманд.

Эталон `tests/golden/` зафиксирован прогоном ядра до раскладки по слоям (change
`layer-forge-core`) с фиксированными часами на моделях `forge.reqs.v1` и `trade.v1`. Выпущенные
дескрипторы и миграции живут в проектах-потребителях, поэтому любое изменение их байтов должно
быть заметно: тест сравнивает побайтно и остаётся регрессионным после раскладки.

Прогон идёт через вход ядра, а не через внутренние функции: вход при раскладке не меняется,
поэтому тело теста от неё не зависит. От раскладки зависит только способ зафиксировать часы
выпуска — его держит один помощник `_frozen`.

Правки версий подобраны так, чтобы выпуск прошёл каждую операцию дельты: добавление,
переименование, смену типа и удаление поля, обязательность с версии, добавление и удаление
типа узла, перечисления и его значений, связи и её сигнатуры, а также версию без операций
и столкновение меток времени двух выпусков в одну секунду.
"""

import contextlib
import io
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import yaml
from forge_model.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "model"
GOLDEN = Path(__file__).parent / "golden"

#: Часы выпусков. Свёртка и две версии идут в разные дни; последний выпуск `trade.v1`
#: приходится на ту же секунду, что и предыдущий, — имена его файлов сдвигаются.
BASELINE = datetime(2026, 9, 15, 14, 22, 33, tzinfo=UTC)
SECOND = datetime(2026, 9, 16, 9, 0, 0, tzinfo=UTC)
THIRD = datetime(2026, 9, 17, 18, 30, 0, tzinfo=UTC)

Mutate = Callable[[Any], None]


@contextlib.contextmanager
def _frozen(moment: datetime) -> Iterator[None]:
    """Зафиксировать часы выпуска: метка времени входит в имена файлов миграций."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    with mock.patch("forge_model.release.infrastructure.clock.datetime", Frozen):
        yield


def _edit(path: Path, mutate: Mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _fields(mutate_field: Callable[[dict[str, Any]], None]) -> Mutate:
    def apply(data: Any) -> None:
        for field in data["fields"]:
            mutate_field(field)

    return apply


def _version(version: str, also: Mutate | None = None) -> Mutate:
    def apply(data: Any) -> None:
        data["version"] = version
        if also is not None:
            also(data)

    return apply


# --- forge.reqs.v1 --------------------------------------------------------


def _reqs_1_3_0(model: Path) -> None:
    """Поле добавлено, переименовано и сменило тип; обязательность с версии; новые значение
    перечисления, перечисление, тип узла и связь; кодомен связи расширен, кардинальность
    ужесточена."""

    def br(data: Any) -> None:
        data["fields"].append({"id": 6, "name": "owner", "type": "text"})
        for field in data["fields"]:
            if field["id"] == 4:
                field["name"] = "provenance"
            if field["id"] == 2:
                field["type"] = "int"

    def manifest(data: Any) -> None:
        data["enums"]["req_status"]["values"].append({"id": 4, "name": "ARCHIVED"})
        data["enums"]["test_result"] = {
            "id": 2,
            "values": [{"id": 1, "name": "PASS"}, {"id": 2, "name": "FAIL"}],
        }

    def relations(data: Any) -> None:
        realizes = data["relations"][0]
        realizes["to"] = ["BR", "TC"]
        realizes["to_cardinality"] = {"min": 0, "max": 5}
        data["relations"].append(
            {
                "id": 2,
                "name": "verified_by",
                "from": ["FR"],
                "to": ["TC"],
                "from_cardinality": {"min": 0, "max": 3},
                "acyclic": False,
            }
        )

    _edit(model / "types" / "br.yaml", br)
    _edit(
        model / "types" / "fr.yaml",
        lambda data: data["fields"].append(
            {"id": 3, "name": "due", "type": "timestamp", "required": True, "required_since": 3}
        ),
    )
    _write(
        model / "types" / "tc.yaml",
        {
            "type": "TC",
            "id": 3,
            "name": {"ru": "Тест-кейс", "en": "Test Case"},
            "fields": [
                {"id": 1, "name": "title", "type": "text", "required": True},
                {"id": 2, "name": "result", "type": "enum.test_result"},
            ],
        },
    )
    _edit(model / "relations.yaml", relations)
    _edit(model / "_manifest.yaml", _version("1.3.0", manifest))


def _reqs_1_4_0(model: Path) -> None:
    """Поле удалено и закрыто навсегда; обязательность существующего поля с версии; значение
    перечисления переименовано и удалено; удалены перечисление, тип узла и связь; кодомен
    сужен, кардинальность ослаблена."""

    def br(data: Any) -> None:
        data["fields"] = [field for field in data["fields"] if field["id"] != 6]

    def provenance(field: dict[str, Any]) -> None:
        if field["id"] == 4:
            field.update(required=True, required_since=4)

    def manifest(data: Any) -> None:
        status = data["enums"]["req_status"]
        status["values"] = [value for value in status["values"] if value["id"] != 4]
        for value in status["values"]:
            if value["id"] == 3:
                value["name"] = "WITHDRAWN"
        del data["enums"]["test_result"]

    def relations(data: Any) -> None:
        data["relations"] = [item for item in data["relations"] if item["name"] != "verified_by"]
        realizes = data["relations"][0]
        realizes["to"] = ["BR"]
        del realizes["to_cardinality"]

    _edit(model / "types" / "br.yaml", br)
    _edit(model / "types" / "br.yaml", _fields(provenance))
    (model / "types" / "tc.yaml").unlink()
    _edit(model / "relations.yaml", relations)
    _edit(model / "_manifest.yaml", _version("1.4.0", manifest))


# --- trade.v1 -------------------------------------------------------------


def _trade_1_1_0(model: Path) -> None:
    """Поле добавлено; существующее поле обязательно с версии; кардинальность ужесточена,
    домен связи расширен, связь добавлена."""

    def active(field: dict[str, Any]) -> None:
        if field["name"] == "active":
            field.update(required=True, required_since=1)

    def relations(data: Any) -> None:
        by_name = {item["name"]: item for item in data["relations"]}
        by_name["shipped_by"]["to_cardinality"] = {"min": 0, "max": 1}
        by_name["belongs_to"]["from"] = ["ITEM", "SHIP"]
        data["relations"].append({"id": 6, "name": "supersedes", "from": ["ORD"], "to": ["ORD"]})

    _edit(
        model / "types" / "ord.yaml",
        lambda data: data["fields"].append({"id": 6, "name": "discount", "type": "int"}),
    )
    _edit(model / "types" / "prod.yaml", _fields(active))
    _edit(model / "relations.yaml", relations)
    _edit(model / "_manifest.yaml", _version("1.1.0"))


def _trade_1_2_0(model: Path) -> None:
    """Поле переименовано, удалено и добавлено; значение перечисления добавлено; связь
    переименована."""

    def comment(field: dict[str, Any]) -> None:
        if field["name"] == "comment":
            field["name"] = "note"

    def ship(data: Any) -> None:
        data["fields"] = [field for field in data["fields"] if field["name"] != "tracking"]

    def manifest(data: Any) -> None:
        data["enums"]["payment_method"]["values"].append({"id": 4, "name": "CRYPTO"})

    def relations(data: Any) -> None:
        for item in data["relations"]:
            if item["name"] == "refers_to":
                item["name"] = "points_to"

    _edit(model / "types" / "ord.yaml", _fields(comment))
    _edit(model / "types" / "ship.yaml", ship)
    _edit(
        model / "types" / "cust.yaml",
        lambda data: data["fields"].append({"id": 4, "name": "phone", "type": "text"}),
    )
    _edit(model / "relations.yaml", relations)
    _edit(model / "_manifest.yaml", _version("1.2.0", manifest))


def _trade_1_3_0(model: Path) -> None:
    """Структура изменена без операций дельты: связь перестала требовать ацикличности."""

    def relations(data: Any) -> None:
        for item in data["relations"]:
            if item["name"] == "replaces":
                item["acyclic"] = False

    _edit(model / "relations.yaml", relations)
    _edit(model / "_manifest.yaml", _version("1.3.0"))


#: Выпуски после свёртки: версия, правка модели, часы выпуска.
STEPS: dict[str, list[tuple[str, Callable[[Path], None], datetime]]] = {
    "forge.reqs.v1": [
        ("1.3.0", _reqs_1_3_0, SECOND),
        ("1.4.0", _reqs_1_4_0, THIRD),
    ],
    "trade.v1": [
        ("1.1.0", _trade_1_1_0, SECOND),
        ("1.2.0", _trade_1_2_0, THIRD),
        ("1.3.0", _trade_1_3_0, THIRD),
    ],
}


def _produce(name: str, workspace: Path) -> dict[str, bytes]:
    """Провести модель через свёртку и выпуски версий; вернуть вывод подкоманд и файлы выпуска.

    Каталоги передаются ключами относительно корня проекта: напечатанные пути тогда
    не зависят от временного каталога прогона.
    """
    project = workspace / "project"
    model = project / "model" / name
    shutil.copytree(FIXTURES / name, model)
    keys = [
        "--model",
        f"model/{name}",
        "--releases",
        "model/releases",
        "--changelog",
        "changelog",
    ]
    outputs: dict[str, str] = {}

    def run(step: str, command: str, *extra: str) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([command, *keys, *extra])
        assert (code, stderr.getvalue()) == (0, ""), f"{name} {step}: {stderr.getvalue()}"
        outputs[f"output/{len(outputs) + 1:02d}-{step}.txt"] = stdout.getvalue()

    with contextlib.chdir(project):
        run("build", "build")
        run("checks", "checks")
        run("diff", "diff")
        with _frozen(BASELINE):
            run("gen-baseline", "gen", "--baseline")
        for version, change, moment in STEPS[name]:
            change(model)
            run(f"diff-{version}", "diff")
            with _frozen(moment):
                run(f"gen-{version}", "gen")
        run("gen-noop", "gen")
        run("build-final", "build")
        run("checks-final", "checks")

    produced = {path: text.encode("utf-8") for path, text in outputs.items()}
    for root in (project / "changelog", project / "model" / "releases"):
        for path in root.rglob("*"):
            if path.is_file():
                produced[path.relative_to(project).as_posix()] = path.read_bytes()
    taken = model / "_taken.yaml"
    if taken.exists():
        produced[taken.relative_to(project).as_posix()] = taken.read_bytes()
    return produced


def _stored(name: str) -> dict[str, bytes]:
    root = GOLDEN / name
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("name", sorted(STEPS))
def test_выпуск_совпадает_с_эталоном(name, tmp_path):
    produced, stored = _produce(name, tmp_path), _stored(name)

    assert sorted(produced) == sorted(stored), "состав файлов выпуска и вывода"
    for path, content in stored.items():
        assert produced[path].decode("utf-8") == content.decode("utf-8"), path
