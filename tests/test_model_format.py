"""Формат модели: разбор типов узлов, сигнатур связей, занятых номеров, нарушения с местом."""

import pytest
import yaml
from forge_model.contract.domain import Version, compile_descriptor
from forge_model.contract.infrastructure import YamlModelSource


def _read(root):
    return YamlModelSource(root).read()


def _model(root):
    reading = _read(root)
    assert reading.findings == ()
    assert reading.model is not None
    return reading.model


def _type(model, code):
    return next(node for node in model.types if node.code == code)


def _findings(root):
    """Нарушения формата и структуры: модель с ними не компилируется."""
    compilation = compile_descriptor(_read(root))
    assert compilation.descriptor is None
    return [(str(item.place), item.element, item.message) for item in compilation.findings]


def test_тип_узла_разбирается_со_всеми_элементами_формата(model_root):
    model = _model(model_root)

    assert model.package == "forge.reqs"
    assert model.version == Version(1, 2, 0)

    br = _type(model, "BR")
    assert br.id == 1
    assert br.name_ru == "Бизнес-требование"
    assert br.name_en == "Business Requirement"
    assert br.table == "br_revision"

    title = br.fields[0]
    assert (title.id, title.name, title.required) == (1, "title", True)
    assert title.type_text == "text"

    status = next(f for f in br.fields if f.name == "status")
    assert (status.kind, status.type) == ("enum", "req_status")


def test_перечисление_разбирается_из_манифеста(model_root):
    status = next(enum for enum in _model(model_root).enums if enum.name == "req_status")

    assert [v.name for v in status.values] == ["DRAFT", "APPROVED", "RETIRED"]


def test_сигнатура_связи_разбирается(model_root):
    realizes = _model(model_root).relations[0]

    assert realizes.name == "realizes"
    assert realizes.sources == ("FR",)
    assert realizes.targets == ("BR",)
    assert realizes.source_cardinality.min == 1
    assert realizes.source_cardinality.max is None
    assert realizes.acyclic is True


@pytest.mark.parametrize("missing", ["from", "to"])
def test_связь_без_домена_или_кодомена_отвергается(model_copy, missing):
    path = model_copy / "relations.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["relations"][0][missing] = []
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert any("связи" in message for _, _, message in _findings(model_copy))


def test_занятые_номера_имена_и_коды_разбираются(model_root):
    br = _type(_model(model_root), "BR")

    assert br.taken.fields == (7,)
    assert br.taken.names == ("priority",)
    assert br.taken.codes == (19,)


def test_обязательность_начиная_с_версии_разбирается(model_root):
    br = _type(_model(model_root), "BR")

    rationale = next(f for f in br.fields if f.name == "rationale")
    assert rationale.required is True
    assert rationale.required_since == 2

    origin = next(f for f in br.fields if f.name == "origin")
    assert origin.required is False
    assert origin.required_since is None


def test_required_since_без_обязательности_отвергается(model_copy):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].append({"id": 6, "name": "note", "type": "text", "required_since": 2})
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert any("required_since" in message for _, _, message in _findings(model_copy))


def test_неизвестный_тип_поля_отвергается(model_copy):
    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"][0]["type"] = "money"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert any("неизвестный тип" in message for _, _, message in _findings(model_copy))


def test_сообщение_об_ошибке_называет_место(model_copy):
    (model_copy / "types" / "br.yaml").write_text("type: BR\nid: 1\n", encoding="utf-8")

    found = [item for item in _findings(model_copy) if item[0].startswith("types/br.yaml")]
    assert found == [("types/br.yaml:1", "тип", "отсутствуют обязательные ключи: fields, name")]


# --- чтение с номерами строк ---------------------------------------------


def test_синтаксическая_ошибка_называет_файл_и_строку(model_copy):
    (model_copy / "types" / "fr.yaml").write_text("type: FR\nid: 2: 3\nname: x\n", encoding="utf-8")

    reading = _read(model_copy)

    assert [(str(item.place), item.element) for item in reading.findings] == [
        ("types/fr.yaml:2", "файл")
    ]
    assert "не разбирается как YAML" in reading.findings[0].message
    assert reading.model is not None
    assert [node.code for node in reading.model.types] == ["BR"], "остальные файлы прочитаны"


def test_два_нарушения_формата_в_одном_файле(model_copy):
    path = model_copy / "types" / "br.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[8] = "  - { id: 1, name: title, type: text, required: да }"
    lines[10] = "  - { id: 3, name: status, type: money, required: true }"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    found = [(str(item.place), item.message) for item in _read(model_copy).findings]

    assert found == [
        ("types/br.yaml:9", "required должен быть true или false"),
        (
            "types/br.yaml:11",
            "неизвестный тип 'money': ожидается один из text, int, bool, timestamp, uuid"
            " либо enum.<имя> / ref.<ТИП>",
        ),
    ]


def test_нарушения_формата_разных_файлов_за_один_прогон(model_copy):
    manifest = model_copy / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("version: 1.2.0", "version: 1.2"),
        encoding="utf-8",
    )
    relations = model_copy / "relations.yaml"
    relations.write_text(
        relations.read_text(encoding="utf-8").replace("acyclic: true", "acyclic: всегда"),
        encoding="utf-8",
    )

    reading = _read(model_copy)

    assert [str(item.place) for item in reading.findings] == [
        "_manifest.yaml:2",
        "relations.yaml:7",
    ]
    assert reading.model is None, "без версии модель не собирается"
