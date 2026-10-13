"""Контракты чтения модуля хранилища, модель расхождения и исходы его сценариев.

Каждый контракт отвечает на один вопрос (APB-005 (2)): какая модель в рабочем каталоге,
какие файлы выпущены и с какими суммами, какие колонки и какой отпечаток версии в хранилище,
каков текст запроса правила и кто его нарушает. Контракта записи здесь нет: сценарии модуля —
запросы, они хранилище не меняют.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from ...contract.domain import Finding, ModelReading
from ..domain import IntegrityRule

#: Исходы сценариев модуля.
LISTED: Final = "listed"
VERIFIED: Final = "verified"
DRIFTED: Final = "drifted"
REJECTED: Final = "rejected"


class ModelSource(Protocol):
    """Модель рабочего каталога: объекты модели и нарушения формата её файлов."""

    def read(self) -> ModelReading: ...


class ReleasedFile(Protocol):
    """Выпущенный файл: адрес, версия выпуска, записанная и фактическая контрольные суммы."""

    @property
    def address(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def recorded(self) -> str: ...

    @property
    def actual(self) -> str | None: ...


class RegistryEntries(Protocol):
    """Файлы, записанные в реестр выпусков, с пересчитанными по диску суммами."""

    def files(self) -> tuple[ReleasedFile, ...]: ...


class SchemaInspector(Protocol):
    """Фактическая схема хранилища: колонки таблиц и отпечаток версии модели."""

    def columns(self) -> Mapping[str, frozenset[str]]:
        """Колонки каждой таблицы хранилища."""
        ...

    def stamp(self) -> tuple[str, str] | None:
        """Версия и хеш модели, записанные замыкающей миграцией; `None` — отпечатка нет."""
        ...


class IntegrityQueries(Protocol):
    """Текст запроса, возвращающего нарушителей правила целостности."""

    def sql(self, rule: IntegrityRule) -> str: ...


class IntegrityProbe(Protocol):
    """Выполнение запроса целостности: нарушители — узлы или связи."""

    def offenders(self, sql: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """Расхождение: место — файл и строка либо элемент хранилища — и что с ним не так."""

    place: str
    message: str


def discrepancies(findings: Iterable[Finding]) -> tuple[Discrepancy, ...]:
    """Перевести нарушения домена в расхождения выходного контракта."""
    return tuple(
        Discrepancy(str(finding.place), f"{finding.element}: {finding.message}")
        for finding in findings
    )
