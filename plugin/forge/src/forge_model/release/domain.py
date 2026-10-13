"""Домен выпуска: шаги миграции, раскладка каталога миграций, агрегат выпуска, контракт записи.

Шаг миграции — нейтральная операция над схемой, выведенная из дельты модели: она называет,
что должно измениться, но не знает ни диалекта, ни имени файла. Диалект превращает шаг
в операторы СУБД, раскладка — в имя и место файла (design D6 change `layer-forge-core`).

Раскладка — правила норм `MDL-030..032`: каталог миграции определяется элементом модели,
имя файла — меткой времени, порядок применения — явными включениями, а не именами файлов.
Текст миграции выводится из модели и дельты правилами этого домена, поэтому он — содержимое
агрегата выпуска, а не внешнее значение.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

from ..contract import domain as contract
from ..contract.domain import (
    Delta,
    Descriptor,
    EnumValue,
    Field,
    NodeType,
    RelationSignature,
    TakenNumbers,
    Version,
)

#: Автор changeset'ов выпущенных миграций.
AUTHOR: Final = "model-gen"
#: Каталог элементов, не принадлежащих ни одному типу узла, и замыкающих миграций.
CORE: Final = "core"
#: Каталог сигнатур связей.
RELATIONS: Final = "rel"
#: Порядок каталогов внутри одной версии (MDL-032): общие элементы, типы узлов, связи.
FOLDER_RANK: Final = {CORE: 0, RELATIONS: 2}
TYPE_RANK: Final = 1
#: Имя файла миграции — метка времени до секунды (MDL-031).
NAME_FORMAT: Final = "Version%Y%m%d%H%M%S.sql"


# --- шаги миграции --------------------------------------------------------


@dataclass(frozen=True)
class MigrationStep:
    """Шаг миграции — одна нейтральная операция над схемой.

    `folder` — каталог элемента модели, которому шаг принадлежит (MDL-030); `slug` — часть
    идентификатора changeset'а, выводимая из координат модели. Элементы, которых шаг касается,
    переданы объектами дескриптора; связь, названная одним именем, — `relation_name`.
    """

    kind: str
    folder: str
    slug: str
    comment: str
    type_code: str = ""
    field: Field | None = None
    previous_field: Field | None = None
    node_type: NodeType | None = None
    enum_name: str = ""
    value: EnumValue | None = None
    relation: RelationSignature | None = None
    relation_name: str = ""


def migration_steps(delta: Delta) -> tuple[MigrationStep, ...]:
    """Шаги миграции дельты в порядке применения: общие элементы, типы узлов, связи."""
    steps = [step for operation in delta.operations for step in _steps(operation)]
    return tuple(
        sorted(steps, key=lambda step: (FOLDER_RANK.get(step.folder, TYPE_RANK), step.slug))
    )


def _steps(operation: contract.Operation) -> list[MigrationStep]:
    handler = _HANDLERS.get(operation.kind)
    return handler(operation) if handler else []


def _type_folder(code: str) -> str:
    return code.lower()


#: Суффикс идентификатора changeset'а для каждого шага над колонкой.
COLUMN_SLUG: Final = {
    "add_column": "add",
    "drop_column": "drop",
    "rename_column": "rename",
    "alter_column_type": "retype",
}


def _field(operation: contract.Operation) -> Field:
    assert operation.field is not None, operation
    return operation.field


def _column(operation: contract.Operation, kind: str) -> list[MigrationStep]:
    field = _field(operation)
    return [
        MigrationStep(
            kind=kind,
            folder=_type_folder(operation.type_code),
            slug=f"{operation.type_code}.f{field.id}.{COLUMN_SLUG[kind]}",
            comment=operation.detail,
            type_code=operation.type_code,
            field=field,
            previous_field=operation.previous_field,
        )
    ]


def _added(operation: contract.Operation) -> list[MigrationStep]:
    steps = _column(operation, "add_column")
    field = _field(operation)
    if field.required and field.required_since:
        steps.append(_require(operation.type_code, field, operation.detail))
    return steps


def _required(operation: contract.Operation) -> list[MigrationStep]:
    return [_require(operation.type_code, _field(operation), operation.detail)]


def _require(code: str, field: Field, comment: str) -> MigrationStep:
    return MigrationStep(
        kind="require_since",
        folder=_type_folder(code),
        slug=f"{code}.f{field.id}.require",
        comment=comment,
        type_code=code,
        field=field,
    )


def _node_type(operation: contract.Operation) -> NodeType:
    assert operation.node_type is not None, operation
    return operation.node_type


def _type_added(operation: contract.Operation) -> list[MigrationStep]:
    entry = _node_type(operation)
    return [
        MigrationStep(
            "create_table",
            _type_folder(entry.code),
            f"{entry.code}.create",
            operation.detail,
            type_code=entry.code,
            node_type=entry,
        ),
        MigrationStep(
            "add_node_kind",
            CORE,
            f"kind.{entry.code}.add",
            f"тип узла {entry.code} добавлен в перечень видов узлов",
            type_code=entry.code,
            node_type=entry,
        ),
    ]


def _type_removed(operation: contract.Operation) -> list[MigrationStep]:
    entry = _node_type(operation)
    return [
        MigrationStep(
            "drop_table",
            _type_folder(entry.code),
            f"{entry.code}.drop",
            operation.detail,
            type_code=entry.code,
            node_type=entry,
        )
    ]


def _signature(
    kind: str, suffix: str, *, described: bool = True
) -> Callable[[contract.Operation], list[MigrationStep]]:
    """Шаг над справочником сигнатур связей.

    Изменение кардинальности называет связь одним именем, без сигнатуры (`described=False`):
    выпущенные миграции такой операции несут вместо строк справочника пометку, что сигнатура
    описана в дескрипторе версии. Выпущенное неизменяемо (MDL-035), поэтому поведение
    перенесено как есть.
    """

    def build(operation: contract.Operation) -> list[MigrationStep]:
        assert operation.relation is not None, operation
        return [
            MigrationStep(
                kind,
                RELATIONS,
                f"rel.{operation.relation.name}.{suffix}",
                operation.detail,
                relation=operation.relation if described else None,
                relation_name=operation.relation.name,
            )
        ]

    return build


def _enum_value_added(operation: contract.Operation) -> list[MigrationStep]:
    assert operation.value is not None, operation
    return [
        MigrationStep(
            "add_enum_value",
            CORE,
            f"enum.{operation.enum_name}.{operation.value.name}",
            operation.detail,
            enum_name=operation.enum_name,
            value=operation.value,
        )
    ]


_HANDLERS: Final[dict[str, Callable[[contract.Operation], list[MigrationStep]]]] = {
    contract.FIELD_ADDED: _added,
    contract.FIELD_REMOVED: lambda operation: _column(operation, "drop_column"),
    contract.FIELD_RENAMED: lambda operation: _column(operation, "rename_column"),
    contract.FIELD_TYPE_CHANGED: lambda operation: _column(operation, "alter_column_type"),
    contract.FIELD_REQUIRED: _required,
    contract.TYPE_ADDED: _type_added,
    contract.TYPE_REMOVED: _type_removed,
    contract.ENUM_VALUE_ADDED: _enum_value_added,
    contract.RELATION_ADDED: _signature("insert_signature", "add"),
    contract.RELATION_REMOVED: _signature("delete_signature", "drop"),
    "relation_from_widened": _signature("update_signature", "from_widened"),
    "relation_to_widened": _signature("update_signature", "to_widened"),
    "relation_from_narrowed": _signature("update_signature", "from_narrowed"),
    "relation_to_narrowed": _signature("update_signature", "to_narrowed"),
    contract.RELATION_CARDINALITY: _signature("update_signature", "cardinality", described=False),
}


# --- текст и имя миграции -------------------------------------------------


def migration_text(
    slug: str,
    version: str,
    comment: str,
    statements: Iterable[str],
    rollback: Iterable[str],
    *,
    precondition: str | None = None,
) -> str:
    """Текст миграции — changeset Liquibase формата SQL с откатом и предусловием."""
    lines = ["--liquibase formatted sql", ""]
    lines.append(f"--changeset {AUTHOR}:{slug} labels:model-{version}")
    lines.append(f"--comment: {comment}")
    if precondition:
        lines.append("--preconditions onFail:HALT")
        lines.append(f"--precondition-sql-check expectedResult:1 {precondition}")
    lines += list(statements)
    lines += [f"--rollback {line}" for line in rollback]
    return "\n".join(lines) + "\n"


def closing_comment(previous: Descriptor | None, version: str, delta: Delta) -> str:
    """Пояснение замыкающей миграции версии: переход версий и признак версии без шагов."""
    comment = f"{previous.version if previous else 'начало'} -> {version}"
    if not delta.operations:
        comment += "; схема не меняется"
    return comment


def baseline_comment(descriptor: Descriptor) -> str:
    """Пояснение свёртки модели (MDL-037)."""
    return f"начальная схема модели {descriptor.model} {descriptor.version}"


#: Откат свёртки: начальная схема откатывается пересозданием хранилища.
BASELINE_ROLLBACK: Final = ("-- начальная схема откатывается пересозданием хранилища",)


def stamp_comment(version: str) -> str:
    """Пояснение замыкающей миграции свёртки: отпечаток версии модели."""
    return f"отпечаток модели {version}"


def migration_names(
    folders: Sequence[str], moment: datetime, taken: Mapping[str, Iterable[str]]
) -> tuple[str, ...]:
    """Имена файлов миграций выпуска по их каталогам (MDL-031).

    Имя — метка времени: уникально без общего счётчика и не конфликтует при слиянии веток.
    Метки внутри одного выпуска идут подряд, по секунде на файл. Соседний выпуск может начаться
    в ту же секунду: занятое имя каталога не выдаётся повторно — это молча уничтожило бы уже
    выпущенную миграцию, — берётся следующая свободная секунда.
    """
    base = int(moment.replace(microsecond=0).timestamp())
    occupied = {folder: set(names) for folder, names in taken.items()}
    names: list[str] = []
    for offset, folder in enumerate(folders):
        stamp = base + offset
        used = occupied.setdefault(folder, set())
        while (name := _name(stamp)) in used:
            stamp += 1
        used.add(name)
        names.append(name)
    return tuple(names)


def _name(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, tz=UTC).strftime(NAME_FORMAT)


# --- агрегат выпуска ------------------------------------------------------


def checksum(data: bytes) -> str:
    """Контрольная сумма выпущенного файла: по ней реестр замечает правку (MDL-036)."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Migration:
    """Миграция: каталог, имя файла и текст. Выпущенная миграция неизменяема (MDL-035)."""

    folder: str
    name: str
    text: str

    @property
    def address(self) -> str:
        """Адрес миграции от корня каталога миграций."""
        return f"{self.folder}/{self.name}"

    @property
    def checksum(self) -> str:
        """Контрольная сумма текста: та же, что у записанного файла."""
        return checksum(self.text.encode("utf-8"))


@dataclass(frozen=True)
class RegistryEntry:
    """Запись реестра выпусков: версия, хеш модели и контрольные суммы выпущенных файлов."""

    version: str
    hash: str
    files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Release:
    """Агрегат выпуска — файлы одной версии модели, записываемые вместе.

    Агрегат несёт всё, что пишет выпуск: миграции в порядке применения, дескриптор версии
    с пополненным перечнем занятых номеров и сами добавленные занятые номера — удалённые поля
    вместе с кодом их типа. Порядок применения и запись реестра выводятся из миграций.
    Идентичность выпуска — адреса его миграций: по занятому адресу выпуск не пишется.
    """

    version: Version
    descriptor: Descriptor
    migrations: tuple[Migration, ...]
    taken: tuple[tuple[str, Field], ...] = ()

    @property
    def order(self) -> tuple[str, ...]:
        """Порядок применения: адреса миграций для явных включений `master.yaml` (MDL-032)."""
        return tuple(migration.address for migration in self.migrations)

    @property
    def registry_entry(self) -> RegistryEntry:
        """Запись реестра: контрольные суммы считаются по тексту миграций, а не по диску."""
        return RegistryEntry(
            str(self.version),
            self.descriptor.hash,
            tuple((migration.address, migration.checksum) for migration in self.migrations),
        )


#: Исходы записи выпуска: записан; адрес занят — ничего не записано и не перезаписано.
RELEASE_WRITTEN: Final = "written"
RELEASE_EXISTS: Final = "exists"


class ReleaseRepository(Protocol):
    """Контракт записи выпуска: принимает агрегат целиком, операций чтения не несёт."""

    def add(self, release: Release) -> Literal["written", "exists"]: ...


def taken_fields(delta: Delta) -> tuple[tuple[str, Field], ...]:
    """Поля, удалённые дельтой: их номера и имена занимаются навсегда (MDL-016, MDL-027)."""
    return tuple(
        (operation.type_code, operation.field)
        for operation in delta.operations
        if operation.kind == contract.FIELD_REMOVED and operation.field is not None
    )


def replenished(descriptor: Descriptor, taken: Iterable[tuple[str, Field]]) -> Descriptor:
    """Дескриптор с пополненным перечнем занятых номеров (MDL-017).

    Пересборка идёт в домене: повторно читать файлы модели не нужно. Хеш не меняется —
    перечень занятых номеров в него не входит (MDL-019).
    """
    removed: dict[str, list[Field]] = {}
    for code, field in taken:
        removed.setdefault(code, []).append(field)
    if not removed:
        return descriptor
    return replace(
        descriptor,
        types=tuple(
            replace(node, taken=_occupied(node.taken, removed[node.code]))
            if node.code in removed
            else node
            for node in descriptor.types
        ),
    )


def _occupied(taken: TakenNumbers, fields: Iterable[Field]) -> TakenNumbers:
    fields = list(fields)
    return TakenNumbers(
        fields=tuple(sorted(set(taken.fields) | {field.id for field in fields})),
        names=tuple(sorted(set(taken.names) | {field.name for field in fields})),
        codes=tuple(sorted(set(taken.codes))),
    )
