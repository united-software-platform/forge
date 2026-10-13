"""Применение выпущенных миграций к настоящему пустому PostgreSQL."""

import tempfile
from pathlib import Path

import pytest
import yaml
from forge_model.release.infrastructure.postgres import PostgresDialect

from tests.conftest import baseline, compiled, release

pgserver = pytest.importorskip("pgserver")


@pytest.fixture(scope="module")
def server():
    directory = Path(tempfile.mkdtemp()) / "pgdata"
    instance = pgserver.get_server(str(directory))
    yield instance
    instance.cleanup()


@pytest.fixture
def db(server):
    """Пустая база на каждый тест: схема собирается с нуля."""
    server.psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    return server


def _apply(db, statements):
    """Применить операторы так, чтобы ошибка СУБД роняла тест.

    Через `psql` ошибка ушла бы в stderr и осталась незамеченной — проверка
    превратилась бы в видимость проверки.
    """
    import psycopg

    with psycopg.connect(db.get_uri(), autocommit=True) as connection:
        for statement in statements:
            connection.execute(statement)


def _sql_of(path: Path) -> list[str]:
    """Вынуть операторы из файла миграции, отбросив служебные строки."""
    body = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("--")
    ]
    return [s + ";" for s in "\n".join(body).split(";") if s.strip()]


def test_свёртка_модели_применяется_к_пустой_базе(db, model_root, tmp_path):
    descriptor = compiled(model_root)
    _apply(db, PostgresDialect().baseline_statements(descriptor))

    tables = db.psql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name;"
    )
    for expected in (
        "br_revision",
        "fr_revision",
        "link",
        "model_state",
        "node",
        "node_revision",
        "rel_signature",
    ):
        assert expected in tables

    assert "realizes" in db.psql("SELECT rel FROM rel_signature;")


def test_замыкающая_миграция_пишет_отпечаток(db, model_root, tmp_path):
    descriptor = compiled(model_root)
    out = tmp_path / "changelog"
    emitted = [out / a for a in baseline(model_root, out).released]

    for path in emitted:
        _apply(db, _sql_of(path))

    state = db.psql("SELECT version || ' ' || hash FROM model_state;")
    assert str(descriptor.version) in state
    assert descriptor.hash in state


def test_добавление_поля_применяется_поверх_свёртки(db, model_root, model_copy, tmp_path):
    before = compiled(model_root)
    out = tmp_path / "changelog"
    for path in [out / a for a in baseline(model_root, out).released]:
        _apply(db, _sql_of(path))

    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"].append({"id": 6, "name": "owner", "type": "text"})
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    manifest = model_copy / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["version"] = "1.3.0"
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    after = compiled(model_copy)
    for file in [out / a for a in release(model_copy, out, before).released]:
        _apply(db, _sql_of(file))

    columns = db.psql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'br_revision' ORDER BY column_name;"
    )
    assert "owner" in columns
    assert after.hash in db.psql("SELECT hash FROM model_state;")


def test_обе_дороги_дают_одну_схему(db, server, model_root, model_copy, tmp_path):
    """Схема, собранная по шагам, совпадает со схемой, собранной свёрткой модели."""
    before = compiled(model_root)
    out = tmp_path / "changelog"
    for path in [out / a for a in baseline(model_root, out).released]:
        _apply(db, _sql_of(path))

    path = model_copy / "types" / "br.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["fields"][3] = {"id": 4, "name": "provenance", "type": "text"}
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    manifest = model_copy / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["version"] = "1.3.0"
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    after = compiled(model_copy)

    for file in [out / a for a in release(model_copy, out, before).released]:
        _apply(db, _sql_of(file))
    step_by_step = db.psql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'br_revision' ORDER BY column_name;"
    )

    server.psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    _apply(server, PostgresDialect().baseline_statements(after))
    from_model = server.psql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'br_revision' ORDER BY column_name;"
    )

    assert step_by_step == from_model
