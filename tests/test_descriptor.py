"""Компиляция модели в дескриптор: раскрытие умолчаний, детерминированность, хеш, нарушения."""

import dataclasses
import json

import pytest
import yaml
from forge_model.contract.domain import compile_descriptor, descriptor_document
from forge_model.contract.infrastructure import YamlModelSource

from tests.conftest import compiled


def _dump(descriptor):
    return json.dumps(descriptor_document(descriptor), ensure_ascii=False, sort_keys=True, indent=2)


def _compilation(root):
    return compile_descriptor(YamlModelSource(root).read())


def _messages(root):
    compilation = _compilation(root)
    assert compilation.descriptor is None, "модель с нарушением не компилируется"
    return [finding.message for finding in compilation.findings]


def test_дескриптор_самодостаточен(model_root):
    d = compiled(model_root)

    assert d.model == "forge.reqs"
    assert str(d.version) == "1.2.0"
    assert (d.version.major, d.version.minor, d.version.patch) == (1, 2, 0)

    br = d.type_by_code("BR")
    assert br is not None
    assert br.table == "br_revision"
    assert br.code_pattern == "BR-{NNN}"

    document = descriptor_document(d)
    status = next(f for f in document["types"][0]["fields"] if f["name"] == "status")
    assert status["values"] == ["DRAFT", "APPROVED", "RETIRED"], "перечисление раскрыто на месте"


def test_умолчания_раскрыты(model_root):
    br = compiled(model_root).type_by_code("BR")
    assert br is not None

    origin = next(f for f in br.fields if f.name == "origin")
    assert origin.required is False
    assert origin.required_since is None
    assert origin.column == "origin"

    title = next(f for f in br.fields if f.name == "title")
    assert title.required_since == 0, "обязательное без признака — обязательно с начала"

    rationale = next(f for f in br.fields if f.name == "rationale")
    assert rationale.required_since == 2


def test_поля_дескриптора_упорядочены_по_номеру(model_copy):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].reverse()
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    br = compiled(model_copy).type_by_code("BR")
    assert br is not None
    numbers = [f.id for f in br.fields]
    assert numbers == sorted(numbers)


def test_повторная_компиляция_даёт_тот_же_файл(model_root):
    assert _dump(compiled(model_root)) == _dump(compiled(model_root))


def test_перестановка_полей_не_меняет_дескриптор(model_copy, model_root):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].reverse()
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert _dump(compiled(model_copy)) == _dump(compiled(model_root))


def test_правка_описания_не_меняет_хеш(model_copy, model_root):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["description"] = "совсем другое пояснение"
    raw["fields"][0]["description"] = "и здесь тоже"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    changed, original = compiled(model_copy), compiled(model_root)
    assert changed.hash == original.hash
    assert changed.types[0].description != original.types[0].description


def test_правка_структуры_меняет_хеш(model_copy, model_root):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].append({"id": 6, "name": "owner", "type": "text"})
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert compiled(model_copy).hash != compiled(model_root).hash


def test_смена_разряда_patch_не_меняет_хеш(model_copy, model_root):
    path = model_copy / "_manifest.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["version"] = "1.2.7"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert compiled(model_copy).hash == compiled(model_root).hash


def test_номер_версии_в_хеш_не_входит(model_copy, model_root):
    """Хеш описывает содержание модели. Повышение версии само по себе содержания не меняет,
    иначе случай «версию повысили, модель не тронули» нельзя было бы отличить от правки."""
    path = model_copy / "_manifest.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["version"] = "1.3.0"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    changed, original = compiled(model_copy), compiled(model_root)
    assert changed.hash == original.hash
    assert changed.version != original.version


def test_дескриптор_неизменяем(model_root):
    """Сценарий `core-architecture`: присваивание полю дескриптора отвергается языком."""
    descriptor = compiled(model_root)

    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.hash = "sha256:другой"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda raw: raw["fields"].append({"id": 1, "name": "other", "type": "text"}),
            "номер поля",
        ),
        (lambda raw: raw["fields"].append({"id": 9, "name": "title", "type": "text"}), "имя поля"),
        (lambda raw: raw["fields"].append({"id": 7, "name": "again", "type": "text"}), "занятым"),
        (
            lambda raw: raw["fields"].append({"id": 8, "name": "note", "type": "enum.missing"}),
            "перечисление",
        ),
        (lambda raw: raw["fields"].append({"id": 8, "name": "note", "type": "ref.XX"}), "тип узла"),
    ],
)
def test_валидация_ловит_нарушения(model_copy, mutate, expected):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert any(expected in message for message in _messages(model_copy))


def test_связь_на_несуществующий_тип_отвергается(model_copy):
    path = model_copy / "relations.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["relations"][0]["to"] = ["ZZ"]
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert any("несуществующий тип узла" in message for message in _messages(model_copy))


# --- правило структуры: перечень всех нарушений ----------------------------


def _replace(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_два_нарушения_в_одном_файле(model_copy):
    """Сценарий дельты `model-contract`: неверный код типа и повторный номер поля."""
    path = model_copy / "types" / "br.yaml"
    _replace(path, "type: BR", "type: br")
    _replace(path, "{ id: 2, name: value", "{ id: 1, name: value")

    compilation = _compilation(model_copy)

    assert compilation.descriptor is None
    found = [(str(item.place), item.message) for item in compilation.findings]
    assert (
        "types/br.yaml:1",
        "значение 'br' должно записываться 2-10 заглавных латинских букв",
    ) in found
    assert ("types/br.yaml:10", "номер поля 1 встречается дважды") in found


def test_нарушения_в_разных_файлах(model_copy):
    """Сценарий дельты `model-contract`: дефекты в манифесте и в сигнатурах связей."""
    _replace(model_copy / "_manifest.yaml", "name: DRAFT", "name: draft")
    _replace(model_copy / "relations.yaml", "to: [BR]", "to: [ZZ]")

    found = [(str(item.place), item.message) for item in _compilation(model_copy).findings]

    assert found == [
        ("_manifest.yaml:8", "значение 'draft' должно записываться ЗАГЛАВНЫМИ_С_ПОДЧЁРКИВАНИЕМ"),
        ("relations.yaml:2", "ссылка на несуществующий тип узла 'ZZ'"),
    ]


def test_нарушения_формата_и_структуры_названы_вместе(model_copy):
    """Синтаксическая ошибка одного файла не останавливает проверку остальных."""
    (model_copy / "types" / "fr.yaml").write_text("type: FR\nid: 2: 3\n", encoding="utf-8")
    _replace(model_copy / "types" / "br.yaml", "{ id: 2, name: value", "{ id: 1, name: value")

    found = [str(item.place) for item in _compilation(model_copy).findings]

    assert found == ["relations.yaml:2", "types/br.yaml:10", "types/fr.yaml:2"]
