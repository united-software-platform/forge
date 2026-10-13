"""Генерация миграций: раскладка, именование, порядок, замыкающая миграция, свёртка."""

import yaml

from tests.conftest import baseline, compiled, release


def _edit(root, mutate, version, file="types/br.yaml"):
    path = root / file
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    manifest = root / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return compiled(root)


def _emit(model_root, model_copy, mutate, out, version="1.3.0", file="types/br.yaml"):
    before = compiled(model_root)
    _edit(model_copy, mutate, version, file)
    return before, release(model_copy, out, before)


def _files(out, output):
    return [out / address for address in output.released]


def test_добавление_поля_кладётся_в_каталог_типа(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"
    _, output = _emit(
        model_root,
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        out,
    )

    assert "br/Version20260915142233.sql" in output.released
    body = (out / "br" / "Version20260915142233.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE br_revision ADD COLUMN owner text;" in body
    assert "--rollback ALTER TABLE br_revision DROP COLUMN owner;" in body
    assert "--changeset model-gen:BR.f6.add labels:model-1.3.0" in body


def test_переименование_выпускает_rename(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"
    _emit(
        model_root,
        model_copy,
        lambda raw: raw["fields"].__setitem__(3, {"id": 4, "name": "provenance", "type": "text"}),
        out,
    )
    body = (out / "br" / "Version20260915142233.sql").read_text(encoding="utf-8")
    assert "RENAME COLUMN origin TO provenance;" in body
    assert "--rollback ALTER TABLE br_revision RENAME COLUMN provenance TO origin;" in body


def test_удаление_поля_выпускается_с_предупреждением(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"
    _, output = _emit(model_root, model_copy, lambda raw: raw["fields"].pop(3), out)

    body = (out / "br" / "Version20260915142233.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE br_revision DROP COLUMN origin;" in body
    assert any(line.startswith("ВНИМАНИЕ") for line in output.summary), "предупреждение выдано"
    assert "данные колонки origin будут удалены" in "\n".join(output.summary)


def test_замыкающая_миграция_несёт_хеш_и_предусловие(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"
    before, output = _emit(
        model_root,
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        out,
    )
    after = compiled(model_copy)

    closing = _files(out, output)[-1].read_text(encoding="utf-8")
    assert "--preconditions onFail:HALT" in closing
    assert before.hash in closing, "предусловие сверяет прежний хеш"
    assert f"UPDATE model_state SET version = '1.3.0', hash = '{after.hash}';" in closing


def test_версия_без_изменений_схемы_выпускает_замыкающую(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"

    def mutate(raw):
        raw["fields"] = [f for f in raw["fields"] if f["id"] != 4]
        raw.setdefault("taken", {}).setdefault("fields", []).append(4)

    _, output = _emit(model_root, model_copy, mutate, out)

    assert len(output.released) == 2, "удаление колонки и замыкающая"
    assert "схема не меняется" not in _files(out, output)[-1].read_text(encoding="utf-8")


def test_порядок_в_master_топологический(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"
    before = compiled(model_root)
    (model_copy / "types" / "tc.yaml").write_text(
        yaml.safe_dump(
            {
                "type": "TC",
                "id": 3,
                "name": {"ru": "Тест-кейс", "en": "Test Case"},
                "fields": [{"id": 1, "name": "title", "type": "text", "required": True}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    rel = model_copy / "relations.yaml"
    raw = yaml.safe_load(rel.read_text(encoding="utf-8"))
    raw["relations"].append({"id": 2, "name": "verified_by", "from": ["FR"], "to": ["TC"]})
    rel.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        "1.3.0",
    )

    release(model_copy, out, before)
    order = [
        e["include"]["file"]
        for e in yaml.safe_load((out / "master.yaml").read_text(encoding="utf-8"))[
            "databaseChangeLog"
        ]
    ]

    kind_index = next(
        i for i, f in enumerate(order) if "kind.TC" in (out / f).read_text(encoding="utf-8")
    )
    table_index = next(i for i, f in enumerate(order) if f.startswith("tc/"))
    rel_index = next(i for i, f in enumerate(order) if f.startswith("rel/"))
    assert kind_index < table_index < rel_index, "общие элементы, затем типы, затем связи"
    assert order[-1].startswith("core/"), "замыкающая миграция последняя"


def test_свёртка_модели_создаёт_всю_схему(model_root, tmp_path):
    out = tmp_path / "changelog"
    descriptor = compiled(model_root)
    files = _files(out, baseline(model_root, out))

    body = files[0].read_text(encoding="utf-8")
    for fragment in (
        "CREATE TYPE req_status AS ENUM ('DRAFT', 'APPROVED', 'RETIRED');",
        "CREATE TYPE node_kind AS ENUM ('BR', 'FR');",
        "CREATE TABLE node (",
        "CREATE TABLE br_revision (",
        "CREATE TABLE rel_signature (",
        "INSERT INTO rel_signature (rel, src_kind, dst_kind",
    ):
        assert fragment in body, fragment
    assert "CHECK (mm_version < 2 OR rationale IS NOT NULL) NOT VALID" in body
    assert descriptor.hash in files[-1].read_text(encoding="utf-8")


def test_метки_времени_в_одном_прогоне_не_совпадают(model_root, model_copy, tmp_path):
    out = tmp_path / "changelog"

    def mutate(raw):
        raw["fields"].append({"id": 6, "name": "owner", "type": "text"})
        raw["fields"].append({"id": 8, "name": "note", "type": "text"})

    _, output = _emit(model_root, model_copy, mutate, out)

    names = [path.name for path in _files(out, output)]
    assert len(names) == len(set(names)), "имена уникальны"


def test_повторный_прогон_не_создаёт_файлов(model_root, tmp_path):
    out = tmp_path / "changelog"

    output = release(model_root, out, compiled(model_root))

    assert output.released == ()
    assert not out.exists() or not list(out.rglob("*.sql"))


def test_соседний_выпуск_не_перезаписывает_файл(model_root, model_copy, tmp_path):
    """Два выпуска подряд могут прийтись на одну секунду: занятое имя не перезаписывается."""
    out = tmp_path / "changelog"
    first = compiled(model_root)
    second = _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 6, "name": "owner", "type": "text"}),
        "1.3.0",
    )
    emitted_first = _files(out, release(model_copy, out, first))

    _edit(
        model_copy,
        lambda raw: raw["fields"].append({"id": 8, "name": "note", "type": "text"}),
        "1.4.0",
    )
    emitted_second = _files(out, release(model_copy, out, second))

    paths = [p.resolve() for p in emitted_first + emitted_second]
    assert len(paths) == len(set(paths)), "имена не пересекаются между выпусками"
    for path in emitted_first:
        assert "model-1.3.0" in path.read_text(encoding="utf-8"), "первый выпуск не перезаписан"
