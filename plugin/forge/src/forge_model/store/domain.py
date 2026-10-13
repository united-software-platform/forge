"""Домен хранилища: правила целостности, сверка схемы с моделью, неизменяемость выпущенного.

Нижние и верхние границы кардинальности, ацикличность и подтверждённые ревизии целей —
состояние данных, а не схемы: схема хранилища их не выражает, поэтому они проверяются
отдельными запросами (MDL-015). Домен решает, какие правила следуют из дескриптора и что
считать расхождением; текст запросов и обращение к хранилищу — инфраструктура (design D7).

Сверка однонаправленная: модель — истина, хранилище обязано ей соответствовать. Расхождения
называются поимённо, чтобы было видно, что ожидали и что нашли.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ..contract.domain import Descriptor, Finding, Place

#: Служебные колонки таблиц ревизий, которых нет в модели.
SERVICE_COLUMNS: Final = frozenset({"node_id", "rev", "kind", "mm_version"})

#: Виды правил целостности.
CARDINALITY_MIN: Final = "cardinality_min"
CARDINALITY_MAX: Final = "cardinality_max"
ACYCLIC: Final = "acyclic"
SUSPECT_LINKS: Final = "suspect_links"

#: Сколько нарушителей называет сообщение о нарушении целостности.
LISTED_OFFENDERS: Final = 5


@dataclass(frozen=True)
class IntegrityRule:
    """Правило целостности: что проверяется запросом, а не схемой хранилища.

    Правило кардинальности называет связь, сторону сигнатуры (`from_cardinality` или
    `to_cardinality`), типы узлов этой стороны и границу; правило ацикличности — связь;
    правило подозрительных связей параметров не имеет.
    """

    name: str
    subject: str
    kind: str
    relation: str = ""
    side: str = ""
    node_types: tuple[str, ...] = ()
    bound: int | None = None


@dataclass(frozen=True)
class IntegrityViolation:
    """Нарушение целостности: правило и узлы или связи, которые его нарушают."""

    check: str
    subject: str
    offenders: tuple[str, ...]

    @property
    def description(self) -> str:
        """Предмет правила и первые нарушители; об остальных — сколько их."""
        listing = ", ".join(self.offenders[:LISTED_OFFENDERS])
        rest = len(self.offenders) - LISTED_OFFENDERS
        tail = f" и ещё {rest}" if rest > 0 else ""
        return f"{self.subject}; нарушители: {listing}{tail}"

    def __str__(self) -> str:
        return f"{self.check}: {self.description}"


@dataclass(frozen=True)
class SchemaDrift:
    """Расхождение схемы хранилища с моделью: где и что не совпало."""

    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"


def integrity_rules(descriptor: Descriptor) -> tuple[IntegrityRule, ...]:
    """Правила целостности дескриптора: кардинальность, ацикличность, подозрительные связи."""
    rules: list[IntegrityRule] = []
    for relation in descriptor.relations:
        for side, node_types, cardinality in (
            ("from_cardinality", relation.sources, relation.source_cardinality),
            ("to_cardinality", relation.targets, relation.target_cardinality),
        ):
            if cardinality.min >= 1:
                rules.append(
                    IntegrityRule(
                        f"{relation.name}.{side}.min",
                        f"узел без обязательной связи {relation.name} (минимум {cardinality.min})",
                        CARDINALITY_MIN,
                        relation.name,
                        side,
                        node_types,
                        cardinality.min,
                    )
                )
            if cardinality.max is not None:
                rules.append(
                    IntegrityRule(
                        f"{relation.name}.{side}.max",
                        f"узел со связями {relation.name} сверх предела "
                        f"(максимум {cardinality.max})",
                        CARDINALITY_MAX,
                        relation.name,
                        side,
                        node_types,
                        cardinality.max,
                    )
                )
    rules += [
        IntegrityRule(
            f"{relation.name}.acyclic",
            f"цикл по связи {relation.name}",
            ACYCLIC,
            relation.name,
        )
        for relation in descriptor.relations
        if relation.acyclic
    ]
    rules.append(
        IntegrityRule(
            "links.suspect",
            "связь подтверждена против устаревшей ревизии цели",
            SUSPECT_LINKS,
        )
    )
    return tuple(rules)


def violation(rule: IntegrityRule, offenders: tuple[str, ...]) -> IntegrityViolation | None:
    """Нарушение правила: есть, если запрос правила вернул нарушителей."""
    if not offenders:
        return None
    return IntegrityViolation(rule.name, rule.subject, offenders)


def expected_columns(descriptor: Descriptor) -> dict[str, frozenset[str]]:
    """Какие колонки таблиц ревизий описаны моделью."""
    return {
        node.table: frozenset({field.column for field in node.fields} | SERVICE_COLUMNS)
        for node in descriptor.types
    }


def schema_drifts(
    expected: Mapping[str, frozenset[str]], actual: Mapping[str, frozenset[str]]
) -> tuple[SchemaDrift, ...]:
    """Расхождения колонок: таблицы и колонки, описанные моделью, против фактических."""
    drifts: list[SchemaDrift] = []
    for table, columns in expected.items():
        if table not in actual:
            drifts.append(SchemaDrift(table, "таблица описана моделью, но в хранилище отсутствует"))
            continue
        drifts += [
            SchemaDrift(f"{table}.{column}", "колонка описана моделью, но в хранилище отсутствует")
            for column in sorted(columns - actual[table])
        ]
        drifts += [
            SchemaDrift(f"{table}.{column}", "колонка есть в хранилище, но модель её не описывает")
            for column in sorted(actual[table] - columns)
        ]
    return tuple(drifts)


def stamp_drifts(descriptor: Descriptor, stamp: tuple[str, str] | None) -> tuple[SchemaDrift, ...]:
    """Расхождение отпечатка версии (MDL-034): хранилище собрано не по этой версии модели."""
    if stamp is None:
        return (
            SchemaDrift("model_state", "отпечаток модели отсутствует: миграции не применялись"),
        )
    version, model_hash = stamp
    if model_hash != descriptor.hash:
        return (
            SchemaDrift(
                "model_state",
                f"хранилище собрано по версии {version}, модель — {descriptor.version}: "
                "применены не все миграции",
            ),
        )
    return ()


def released_file_finding(
    address: str, version: str, recorded: str, actual: str | None
) -> Finding | None:
    """Выпущенный файл изменён или удалён после выпуска (MDL-035, MDL-036)."""
    if actual == recorded:
        return None
    message = "удалён" if actual is None else "изменён после выпуска"
    return Finding(Place(address), f"файл выпуска {version}", message)
