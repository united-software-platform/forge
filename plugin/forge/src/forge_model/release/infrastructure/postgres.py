"""Диалект PostgreSQL: шаги миграции, замыкающая миграция и свёртка модели в операторах СУБД.

Модель диалекта не содержит — всё, что специфично для PostgreSQL, живёт здесь. Второй диалект
встанет рядом за тем же контрактом `MigrationDialect` и получит те же шаги на вход.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from ...contract.domain import Descriptor, Field, NodeType, RelationSignature
from ..domain import MigrationStep


class PostgresDialect:
    """Реализация `MigrationDialect` для PostgreSQL."""

    def render(self, step: MigrationStep) -> tuple[list[str], list[str]]:
        """Операторы шага и операторы его отката."""
        return _RENDERERS[step.kind](step)

    def close_version(
        self, previous_hash: str | None, version: str, model_hash: str
    ) -> tuple[list[str], list[str], str | None]:
        """Замыкающая миграция версии: предусловие на прежнее состояние и запись нового."""
        return close_version(previous_hash, version, model_hash)

    def baseline_statements(self, descriptor: Descriptor) -> list[str]:
        """Полная схема, выведенная из дескриптора: свёртка модели, а не история изменений."""
        return baseline_statements(descriptor)


SCALAR_SQL: Final = {
    "text": "text",
    "int": "integer",
    "bool": "boolean",
    "timestamp": "timestamptz",
    "uuid": "uuid",
}


def column_type(field: Field) -> str:
    """Тип колонки для поля дескриптора."""
    if field.kind == "enum":
        return field.type
    if field.kind == "ref":
        return "bigint"
    return SCALAR_SQL[field.type]


def _field(step: MigrationStep) -> Field:
    assert step.field is not None, step
    return step.field


def _previous(step: MigrationStep) -> Field:
    assert step.previous_field is not None, step
    return step.previous_field


def _add_column(step: MigrationStep) -> tuple[list[str], list[str]]:
    table, field = _table(step.type_code), _field(step)
    return (
        [f"ALTER TABLE {table} ADD COLUMN {field.column} {column_type(field)};"],
        [f"ALTER TABLE {table} DROP COLUMN {field.column};"],
    )


def _drop_column(step: MigrationStep) -> tuple[list[str], list[str]]:
    table, field = _table(step.type_code), _field(step)
    return (
        [f"ALTER TABLE {table} DROP COLUMN {field.column};"],
        # Откат вернёт колонку, но не данные: удаление значений необратимо.
        [f"ALTER TABLE {table} ADD COLUMN {field.column} {column_type(field)};"],
    )


def _rename_column(step: MigrationStep) -> tuple[list[str], list[str]]:
    table, was, now = _table(step.type_code), _previous(step), _field(step)
    return (
        [f"ALTER TABLE {table} RENAME COLUMN {was.column} TO {now.column};"],
        [f"ALTER TABLE {table} RENAME COLUMN {now.column} TO {was.column};"],
    )


def _alter_column_type(step: MigrationStep) -> tuple[list[str], list[str]]:
    table, was, now = _table(step.type_code), _previous(step), _field(step)
    return (
        [
            f"ALTER TABLE {table} ALTER COLUMN {now.column} TYPE {column_type(now)} "
            f"USING {now.column}::{column_type(now)};"
        ],
        [
            f"ALTER TABLE {table} ALTER COLUMN {was.column} TYPE {column_type(was)} "
            f"USING {was.column}::{column_type(was)};"
        ],
    )


def _require_since(step: MigrationStep) -> tuple[list[str], list[str]]:
    return _require(step.type_code, _field(step))


def _require(code: str, field: Field) -> tuple[list[str], list[str]]:
    table = _table(code)
    name = f"{code.lower()}_{field.column}_since_{field.required_since}"
    return (
        [
            f"ALTER TABLE {table} ADD CONSTRAINT {name}\n"
            f"  CHECK (mm_version < {field.required_since} "
            f"OR {field.column} IS NOT NULL) NOT VALID;"
        ],
        [f"ALTER TABLE {table} DROP CONSTRAINT {name};"],
    )


def _create_table(step: MigrationStep) -> tuple[list[str], list[str]]:
    assert step.node_type is not None, step
    return _table_of(step.node_type)


def _table_of(entry: NodeType) -> tuple[list[str], list[str]]:
    columns = [
        "  node_id    bigint not null",
        "  rev        integer not null",
        "  mm_version integer not null",
        f"  kind       node_kind not null default '{entry.code}' check (kind = '{entry.code}')",
    ]
    columns += [f"  {field.column:<10} {column_type(field)}" for field in entry.fields]
    body = ",\n".join(
        [
            *columns,
            "  primary key (node_id, rev)",
            "  foreign key (node_id, rev, mm_version)"
            " references node_revision(node_id, rev, mm_version)",
            "  foreign key (node_id, kind) references node(id, kind)",
        ]
    )
    return (
        [f"CREATE TABLE {_table(entry.code)} (\n{body}\n);"],
        [f"DROP TABLE {_table(entry.code)};"],
    )


def _drop_table(step: MigrationStep) -> tuple[list[str], list[str]]:
    return (
        [f"DROP TABLE {_table(step.type_code)};"],
        ["-- восстановление таблицы с данными невозможно"],
    )


def _add_node_kind(step: MigrationStep) -> tuple[list[str], list[str]]:
    return (
        [f"ALTER TYPE node_kind ADD VALUE IF NOT EXISTS '{step.type_code}';"],
        ["-- значение перечислимого типа PostgreSQL не удаляется"],
    )


def _add_enum_value(step: MigrationStep) -> tuple[list[str], list[str]]:
    assert step.value is not None, step
    return (
        [f"ALTER TYPE {step.enum_name} ADD VALUE IF NOT EXISTS '{step.value.name}';"],
        ["-- значение перечислимого типа PostgreSQL не удаляется"],
    )


def _insert_signature(step: MigrationStep) -> tuple[list[str], list[str]]:
    return (
        signature_rows(step.relation, step.relation_name),
        [f"DELETE FROM rel_signature WHERE rel = '{step.relation_name}';"],
    )


def _delete_signature(step: MigrationStep) -> tuple[list[str], list[str]]:
    name = step.relation_name
    return (
        [
            f"DELETE FROM link WHERE rel = '{name}';",
            f"DELETE FROM rel_signature WHERE rel = '{name}';",
        ],
        ["-- восстановление удалённых рёбер невозможно"],
    )


def _update_signature(step: MigrationStep) -> tuple[list[str], list[str]]:
    name = step.relation_name
    statements = [
        f"DELETE FROM rel_signature WHERE rel = '{name}';",
        *signature_rows(step.relation, name),
    ]
    return (
        statements,
        [f"-- прежняя сигнатура связи {name} восстанавливается предыдущей миграцией"],
    )


def signature_rows(relation: RelationSignature | None, name: str) -> list[str]:
    """Строки справочника сигнатур: по одной на каждое сочетание домена и кодомена."""
    if relation is None:
        return [f"-- сигнатура связи {name} описана в дескрипторе версии"]
    rows = []
    for source in relation.sources:
        for target in relation.targets:
            rows.append(
                "INSERT INTO rel_signature "
                "(rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)\n"
                f"  VALUES ('{relation.name}', "
                f"'{source}', '{target}', "
                f"{relation.source_cardinality.min}, "
                f"{_null(relation.source_cardinality.max)}, "
                f"{relation.target_cardinality.min}, {_null(relation.target_cardinality.max)}, "
                f"{str(relation.acyclic).lower()});"
            )
    return rows


def close_version(
    previous_hash: str | None, version: str, model_hash: str
) -> tuple[list[str], list[str], str | None]:
    """Замыкающая миграция версии: предусловие на прежнее состояние и запись нового."""
    statements = [
        f"UPDATE model_state SET version = '{version}', hash = '{model_hash}';",
    ]
    rollback = ["-- откат версии выполняется откатом миграций этой версии"]
    if previous_hash is None:
        statements = [
            f"INSERT INTO model_state (version, hash) VALUES ('{version}', '{model_hash}');"
        ]
        return statements, rollback, None
    precondition = f"SELECT count(*) FROM model_state WHERE hash = '{previous_hash}'"
    return statements, rollback, precondition


def baseline_statements(descriptor: Descriptor) -> list[str]:
    """Полная схема, выведенная из дескриптора: свёртка модели, а не история изменений."""
    statements: list[str] = []
    for enum in descriptor.enums:
        values = ", ".join(f"'{value.name}'" for value in enum.values)
        statements.append(f"CREATE TYPE {enum.name} AS ENUM ({values});")

    kinds = ", ".join(f"'{entry.code}'" for entry in descriptor.types) or "'NONE'"
    statements.append(f"CREATE TYPE node_kind AS ENUM ({kinds});")

    statements.append(
        "CREATE TABLE model_state (\n  version    text not null,\n  hash       text not null\n);"
    )
    statements.append(
        "CREATE TABLE node (\n"
        "  id         bigint generated always as identity primary key,\n"
        "  kind       node_kind not null,\n"
        "  code_num   integer not null check (code_num between 0 and 999),\n"
        "  created_at timestamptz not null default now(),\n"
        "  retired_at timestamptz,\n"
        "  unique (kind, code_num),\n"
        "  unique (id, kind)\n"
        ");"
    )
    statements.append(
        "CREATE VIEW node_code AS\n"
        "  SELECT id, kind, code_num,\n"
        "         kind::text || '-' || lpad(code_num::text, 3, '0') AS code\n"
        "  FROM node;"
    )
    statements.append(
        "CREATE TABLE node_revision (\n"
        "  node_id    bigint not null references node(id),\n"
        "  rev        integer not null check (rev > 0),\n"
        "  mm_version integer not null,\n"
        "  created_at timestamptz not null default now(),\n"
        "  author     text not null,\n"
        "  primary key (node_id, rev),\n"
        "  unique (node_id, rev, mm_version)\n"
        ");"
    )
    statements.append(
        "CREATE TABLE rel_signature (\n"
        "  rel        text not null,\n"
        "  src_kind   node_kind not null,\n"
        "  dst_kind   node_kind not null,\n"
        "  src_min    integer not null default 0,\n"
        "  src_max    integer,\n"
        "  dst_min    integer not null default 0,\n"
        "  dst_max    integer,\n"
        "  acyclic    boolean not null default true,\n"
        "  primary key (rel, src_kind, dst_kind)\n"
        ");"
    )
    statements.append(
        "CREATE TABLE link (\n"
        "  id         bigint generated always as identity primary key,\n"
        "  rel        text not null,\n"
        "  src_id     bigint not null,\n"
        "  src_kind   node_kind not null,\n"
        "  dst_id     bigint not null,\n"
        "  dst_kind   node_kind not null,\n"
        "  conf_rev   integer not null,\n"
        "  created_at timestamptz not null default now(),\n"
        "  retired_at timestamptz,\n"
        "  foreign key (src_id, src_kind) references node(id, kind),\n"
        "  foreign key (dst_id, dst_kind) references node(id, kind),\n"
        "  foreign key (rel, src_kind, dst_kind) references rel_signature,\n"
        "  foreign key (dst_id, conf_rev) references node_revision(node_id, rev),\n"
        "  unique (rel, src_id, dst_id)\n"
        ");"
    )

    for entry in descriptor.types:
        statements += _table_of(entry)[0]
        for field in entry.fields:
            if field.required and field.required_since:
                statements += _require(entry.code, field)[0]

    for relation in descriptor.relations:
        statements += signature_rows(relation, relation.name)

    return statements


def _table(code: str) -> str:
    return f"{code.lower()}_revision"


def _null(value: int | None) -> str:
    return "null" if value is None else str(value)


_RENDERERS: dict[str, Callable[[MigrationStep], tuple[list[str], list[str]]]] = {
    "add_column": _add_column,
    "drop_column": _drop_column,
    "rename_column": _rename_column,
    "alter_column_type": _alter_column_type,
    "require_since": _require_since,
    "create_table": _create_table,
    "drop_table": _drop_table,
    "add_node_kind": _add_node_kind,
    "add_enum_value": _add_enum_value,
    "insert_signature": _insert_signature,
    "delete_signature": _delete_signature,
    "update_signature": _update_signature,
}
