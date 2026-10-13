"""Сравнение версий, классификация операций и решения гейта совместимости.

Гейт исключений не поднимает: ошибка процесса выпуска — исход «отвергнуто» с нарушением,
неизменная модель — исход «выпускать нечего».
"""

import dataclasses
import json

import pytest
import yaml
from forge_model.contract.domain import (
    BREAKING,
    DESTRUCTIVE,
    NOTHING_TO_RELEASE,
    REJECTED,
    RELEASE,
    SAFE,
    CompatibilityGate,
    Version,
    compile_descriptor,
    descriptor_document,
    diff,
)
from forge_model.contract.infrastructure import YamlModelSource
from forge_model.release.infrastructure.files import ChangelogPaths, FileReleasedDescriptors

from tests.conftest import compiled, release


def _compile(root):
    return compiled(root)


def diff_descriptors(old, new):
    return list(diff(old, new).operations)


def _latest(model, releases, major):
    paths = ChangelogPaths(model, releases, releases.parent / "changelog")
    return FileReleasedDescriptors(paths).latest(major)


def plan_release(current, previous):
    return CompatibilityGate().decide(current, previous)


def _rejected(current, previous):
    """Сообщения отвергнутого решения гейта."""
    decision = plan_release(current, previous)
    assert decision.outcome == REJECTED
    return [finding.message for finding in decision.findings]


def _edit(root, mutate, *, version=None, file="types/br.yaml"):
    path = root / file
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    if version is not None:
        manifest = root / "_manifest.yaml"
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        data["version"] = version
        manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return _compile(root)


# --- дельта ---------------------------------------------------------------


def test_переименование_опознаётся_по_номеру(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].__setitem__(3, {"id": 4, "name": "provenance", "type": "text"}),
        version="1.3.0",
    )

    changes = diff_descriptors(before, after)
    assert [c.kind for c in changes] == ["field_renamed"]
    assert changes[0].operation_class is SAFE
    assert "origin -> provenance" in changes[0].detail


def test_добавление_поля_безопасно(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        version="1.3.0",
    )

    changes = diff_descriptors(before, after)
    assert [(c.kind, c.operation_class) for c in changes] == [("field_added", SAFE)]


def test_удаление_поля_разрушающее_но_не_останавливает(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(model_copy, lambda raw: raw["fields"].pop(3), version="1.3.0")

    plan = plan_release(after, before)
    assert plan.outcome == RELEASE, "разрушающая операция выпуск не останавливает"
    assert [c.kind for c in plan.delta.operations] == ["field_removed"]
    assert plan.delta.operations[0].operation_class is DESTRUCTIVE
    assert "данные колонки origin будут удалены" in plan.delta.operations[0].detail
    assert plan.delta.warnings, "разрушающая операция попадает в предупреждения"


def test_обязательное_поле_без_required_since_ломает_контракт(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].append(
            {"id": 6, "name": "owner", "type": "text", "required": True}
        ),
        version="1.3.0",
    )

    changes = diff_descriptors(before, after)
    assert changes[0].operation_class is BREAKING


def test_обязательное_поле_с_required_since_безопасно(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].append(
            {"id": 6, "name": "owner", "type": "text", "required": True, "required_since": 3}
        ),
        version="1.3.0",
    )

    assert diff_descriptors(before, after)[0].operation_class is SAFE


def test_сужение_кодомена_связи_ломает_контракт(model_root, model_copy):
    before = _compile(model_root)
    _edit(
        model_copy,
        lambda raw: raw["relations"][0].__setitem__("to", ["BR", "FR"]),
        file="relations.yaml",
    )
    widened = _compile(model_copy)
    assert diff_descriptors(before, widened)[0].operation_class is SAFE

    narrowed = diff_descriptors(widened, before)
    assert narrowed[0].kind == "relation_to_narrowed"
    assert narrowed[0].operation_class is BREAKING


def test_ужесточение_кардинальности_ломает_контракт(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy,
        lambda raw: raw["relations"][0].__setitem__("to_cardinality", {"min": 1}),
        file="relations.yaml",
    )

    change = diff_descriptors(before, after)[0]
    assert change.kind == "relation_cardinality"
    assert change.operation_class is BREAKING
    assert "ужесточена" in change.detail


def test_удаление_значения_перечисления_ломает_контракт(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy, lambda raw: raw["enums"]["req_status"]["values"].pop(), file="_manifest.yaml"
    )

    change = diff_descriptors(before, after)[0]
    assert (change.kind, change.operation_class) == ("enum_value_removed", BREAKING)


# --- ошибки процесса ------------------------------------------------------


def test_модель_изменена_без_повышения_версии(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(
        model_copy, lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"})
    )

    assert any("повысьте средний разряд" in message for message in _rejected(after, before))


def test_версия_понижена(model_root, model_copy):
    before = dataclasses.replace(_compile(model_root), version=Version(1, 5, 0))
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        version="1.3.0",
    )

    assert any("версия понижена" in message for message in _rejected(after, before))


def test_версия_повышена_без_изменений(model_root, model_copy):
    before = _compile(model_root)
    after = _edit(model_copy, lambda raw: None, version="1.3.0")

    assert any("структура модели не изменилась" in message for message in _rejected(after, before))


def test_модель_не_изменялась_выпускать_нечего(model_root):
    current = _compile(model_root)

    plan = plan_release(current, current)
    assert plan.outcome == NOTHING_TO_RELEASE
    assert "выпускать нечего" in "\n".join(plan.report())


def test_повторная_выдача_номера_поля(model_root, model_copy):
    before = _compile(model_root)

    def mutate(raw):
        raw["fields"] = [f for f in raw["fields"] if f["id"] != 4]
        raw["fields"].append({"id": 4, "name": "owner", "type": "text"})

    after = _edit(model_copy, mutate, version="1.3.0")
    # дельта показала бы переименование, но номер 4 остаётся тем же полем —
    # повторная выдача ловится только после того, как поле было удалено.
    plan = plan_release(after, before)
    assert [c.kind for c in plan.delta.operations] == ["field_renamed"]


def test_гейт_отвергает_номер_поля_выпущенной_версии(model_root, model_copy):
    """Номер поля выпущенной версии, выданный повторно, отвергается гейтом, а не исключением."""
    before = _compile(model_root)
    taken = dataclasses.replace(
        before,
        types=tuple(
            dataclasses.replace(node, taken=dataclasses.replace(node.taken, fields=(6, 7)))
            if node.code == "BR"
            else node
            for node in before.types
        ),
    )
    after = _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        version="1.3.0",
    )

    decision = plan_release(after, taken)

    lines = (model_copy / "types" / "br.yaml").read_text(encoding="utf-8").splitlines()
    place = f"types/br.yaml:{lines.index('- id: 6') + 1}"
    assert decision.outcome == REJECTED
    assert [(str(item.place), item.message) for item in decision.findings] == [
        (place, "номер поля 6 уже был занят в BR и не может быть выдан повторно")
    ]


def test_номер_удалённого_поля_повторно_не_выдаётся(model_root, model_copy):
    before = _compile(model_root)
    _edit(model_copy, lambda raw: raw["fields"].pop(3), version="1.3.0")
    release(model_copy, model_copy.parent / "changelog", before)

    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].append({"id": 4, "name": "owner", "type": "text"})
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    compilation = compile_descriptor(YamlModelSource(model_copy).read())
    assert compilation.descriptor is None
    assert any("выдан повторно" in finding.message for finding in compilation.findings)


def test_занятые_номера_дописываются_инструментом(model_root, model_copy):
    before = _compile(model_root)
    _edit(model_copy, lambda raw: raw["fields"].pop(3), version="1.3.0")
    output = release(model_copy, model_copy.parent / "changelog", before)
    assert "занято навсегда: BR.4 (origin)" in output.summary

    br = _compile(model_copy).type_by_code("BR")
    assert br is not None
    assert 4 in br.taken.fields and "origin" in br.taken.names


# --- поиск выпущенной версии ---------------------------------------------


def test_находится_последняя_выпущенная_версия(tmp_path, model_root):
    releases = tmp_path / "releases"
    releases.mkdir()
    current = _compile(model_root)
    for version in ("1.1.0", "1.2.0", "2.0.0"):
        (releases / f"{version}.json").write_text(
            json.dumps({**descriptor_document(current), "version": version}), encoding="utf-8"
        )

    previous_of_first, previous_of_second = (
        _latest(model_root, releases, 1),
        _latest(model_root, releases, 2),
    )
    assert previous_of_first is not None and str(previous_of_first.version) == "1.2.0"
    assert previous_of_second is not None and str(previous_of_second.version) == "2.0.0"
    assert _latest(model_root, releases, 3) is None


def test_пополнение_занятых_номеров_не_меняет_хеш(model_root, model_copy):
    """Иначе хеш модели навсегда разошёлся бы с хешем, записанным в хранилище."""
    before = _compile(model_root)
    after = _edit(model_copy, lambda raw: raw["fields"].pop(3), version="1.3.0")
    release(model_copy, model_copy.parent / "changelog", before)

    assert _compile(model_copy).hash == after.hash


# --- агрегат выпуска -----------------------------------------------------


def test_агрегат_выпуска_несёт_пополненный_дескриптор(model_root, model_copy):
    """Пересобранный в домене дескриптор содержит занятые номера, хеш не изменился."""
    from forge_model.release.domain import (
        Migration,
        RegistryEntry,
        Release,
        checksum,
        replenished,
        taken_fields,
    )

    before = _compile(model_root)
    after = _edit(model_copy, lambda raw: raw["fields"].pop(3), version="1.3.0")
    taken = taken_fields(plan_release(after, before).delta)
    migration = Migration("br", "Version20260915142233.sql", "ALTER TABLE br_revision;\n")

    release = Release(after.version, replenished(after, taken), (migration,), taken)

    br = release.descriptor.type_by_code("BR")
    assert br is not None
    assert (br.taken.fields, br.taken.names) == ((4, 7), ("origin", "priority"))
    assert release.descriptor.hash == after.hash
    assert [(code, field.name) for code, field in release.taken] == [("BR", "origin")]
    assert release.order == ("br/Version20260915142233.sql",)
    assert release.registry_entry == RegistryEntry(
        "1.3.0",
        after.hash,
        (("br/Version20260915142233.sql", checksum(b"ALTER TABLE br_revision;\n")),),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        release.migrations = ()  # type: ignore[misc]


def test_реализации_чтения_и_записи_разные_классы():
    """APB-005 (4): запись и чтение выпуска — разные компоненты с общей адресацией."""
    import inspect

    from forge_model.release.infrastructure import files

    writer = files.FileReleaseRepository
    readers = (files.FileReleasedDescriptors, files.FileRegistryEntries, files.FileMigrationNames)

    assert "add" in dir(writer)
    assert not {"latest", "files", "taken"} & set(dir(writer)), "в записи нет операций чтения"
    for reader in readers:
        assert "add" not in dir(reader), reader.__name__
        assert not issubclass(reader, writer) and not issubclass(writer, reader)
    for component in (writer, *readers):
        annotation = inspect.signature(component).parameters["paths"].annotation
        assert annotation == "ChangelogPaths", component.__name__


def test_выпуск_по_занятому_адресу_не_перезаписывается(model_root, tmp_path):
    """APB-006 (1)–(3): идентичность выпуска — адреса миграций; занятый адрес не перезаписан."""
    from forge_model.release.domain import RELEASE_EXISTS, RELEASE_WRITTEN, Migration, Release
    from forge_model.release.infrastructure.files import ChangelogPaths, FileReleaseRepository

    descriptor = _compile(model_root)
    paths = ChangelogPaths(tmp_path / "model", tmp_path / "releases", tmp_path / "changelog")
    repository = FileReleaseRepository(paths)
    name = "Version20260915142233.sql"

    first = Release(descriptor.version, descriptor, (Migration("core", name, "-- первый\n"),))
    second = Release(descriptor.version, descriptor, (Migration("core", name, "-- второй\n"),))

    assert repository.add(first) == RELEASE_WRITTEN
    assert repository.add(second) == RELEASE_EXISTS
    assert paths.migration(f"core/{name}").read_text(encoding="utf-8") == "-- первый\n"
    assert len(yaml.safe_load(paths.registry.read_text(encoding="utf-8"))) == 1
