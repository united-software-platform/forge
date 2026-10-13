"""Хранилище PostgreSQL: схема, отпечаток версии и запросы проверок целостности.

Текст запросов — знание диалекта, поэтому он здесь, а не в правилах домена. Соединение
открывается на каждый запрос: сверка читает и ничего не меняет, а открытое между запросами
соединение пришлось бы кому-то закрывать. Недоступное хранилище — ошибка окружения с кодом `2`.

Библиотека доступа к хранилищу импортируется при первом запросе: подкоманды, которым
хранилище не нужно, её не загружают.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from ..errors import EnvironmentFault
from .domain import ACYCLIC, CARDINALITY_MIN, SUSPECT_LINKS, IntegrityRule

#: Запрос строк: текст SQL — строки результата.
Fetch = Callable[[str], list[tuple[Any, ...]]]

COLUMNS_SQL: Final = (
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema = 'public' ORDER BY table_name, column_name;"
)
STATE_SQL: Final = "SELECT version, hash FROM model_state;"

#: Колонка связи, по которой считается кардинальность стороны сигнатуры.
SIDE_COLUMN: Final = {"from_cardinality": "src_id", "to_cardinality": "dst_id"}


class PostgresSession:
    """Запросы к хранилищу по строке подключения."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def fetch(self, sql: str) -> list[tuple[Any, ...]]:
        import psycopg

        try:
            connection = psycopg.connect(self._dsn, autocommit=True)
        except psycopg.OperationalError as error:
            raise EnvironmentFault(
                f"хранилище недоступно: {error}".strip(), where="verify"
            ) from error
        with connection:
            rows: list[tuple[Any, ...]] = connection.execute(sql).fetchall()
        return rows


class PostgresSchemaInspector:
    """Реализация `SchemaInspector`: колонки таблиц и отпечаток версии модели."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch

    def columns(self) -> dict[str, frozenset[str]]:
        actual: dict[str, set[str]] = {}
        for table, column in self._fetch(COLUMNS_SQL):
            actual.setdefault(table, set()).add(column)
        return {table: frozenset(columns) for table, columns in actual.items()}

    def stamp(self) -> tuple[str, str] | None:
        rows = self._fetch(STATE_SQL)
        if not rows:
            return None
        version, model_hash = rows[0]
        return str(version), str(model_hash)


class PostgresIntegrityProbe:
    """Реализация `IntegrityProbe`: нарушители — значения первой колонки результата."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch

    def offenders(self, sql: str) -> tuple[str, ...]:
        return tuple(str(row[0]) for row in self._fetch(sql))


class PostgresIntegrityQueries:
    """Реализация `IntegrityQueries`: запросы, возвращающие нарушителей правила."""

    def sql(self, rule: IntegrityRule) -> str:
        if rule.kind == ACYCLIC:
            return _acyclic(rule.relation)
        if rule.kind == SUSPECT_LINKS:
            return _suspect_links()
        condition = f"< {rule.bound}" if rule.kind == CARDINALITY_MIN else f"> {rule.bound}"
        return _cardinality(rule.relation, SIDE_COLUMN[rule.side], rule.node_types, condition)


def _cardinality(relation: str, column: str, node_types: tuple[str, ...], condition: str) -> str:
    """Узлы, у которых число связей вышло за границу."""
    kinds = ", ".join(f"'{code}'" for code in node_types)
    return (
        "SELECT n.id, n.kind, count(l.id) AS actual\n"
        "FROM node n\n"
        f"LEFT JOIN link l ON l.{column} = n.id AND l.rel = '{relation}'\n"
        "  AND l.retired_at IS NULL\n"
        f"WHERE n.retired_at IS NULL AND n.kind IN ({kinds})\n"
        "GROUP BY n.id, n.kind\n"
        f"HAVING count(l.id) {condition};"
    )


def _acyclic(relation: str) -> str:
    """Узлы, с которых обход связи возвращается в них же."""
    return (
        "WITH RECURSIVE walk(root, node, depth) AS (\n"
        "  SELECT src_id, dst_id, 1 FROM link\n"
        f"   WHERE rel = '{relation}' AND retired_at IS NULL\n"
        "  UNION ALL\n"
        "  SELECT w.root, l.dst_id, w.depth + 1\n"
        "  FROM walk w\n"
        f"  JOIN link l ON l.src_id = w.node AND l.rel = '{relation}'\n"
        "   AND l.retired_at IS NULL\n"
        "  WHERE w.depth < 64\n"
        ")\n"
        "SELECT DISTINCT root FROM walk WHERE node = root;"
    )


def _suspect_links() -> str:
    """Связи, подтверждённые против устаревшей ревизии цели."""
    return (
        "SELECT l.id, l.rel, l.conf_rev, max(r.rev) AS current_rev\n"
        "FROM link l\n"
        "JOIN node_revision r ON r.node_id = l.dst_id\n"
        "WHERE l.retired_at IS NULL\n"
        "GROUP BY l.id, l.rel, l.conf_rev\n"
        "HAVING l.conf_rev < max(r.rev);"
    )
