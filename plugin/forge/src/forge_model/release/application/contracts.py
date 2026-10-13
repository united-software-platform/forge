"""Контракты слоя приложения выпуска: диалект миграций, часы, чтение модели и выпусков.

Диалект — то, что выпуску нужно от СУБД: операторы шага миграции, замыкающая миграция версии
и свёртка модели. Контракт допускает второй диалект, но не добавляет его (design D6).

Чтение модели и выпущенных дескрипторов объявлено здесь заново, а не взято из модуля
контракта модели: слой приложения одного модуля не импортирует слой приложения другого.
Реализации общие — контракты структурные, им подходит один адаптер.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from ...contract.domain import Descriptor, Finding, ModelReading
from ..domain import MigrationStep

#: Исходы сценариев выпуска.
RELEASED: Final = "released"
NOTHING_TO_RELEASE: Final = "nothing_to_release"
REJECTED: Final = "rejected"


class MigrationDialect(Protocol):
    """Диалект СУБД: операторы и откат шага, замыкающая миграция, свёртка модели."""

    def render(self, step: MigrationStep) -> tuple[list[str], list[str]]:
        """Операторы шага и операторы его отката."""
        ...

    def close_version(
        self, previous_hash: str | None, version: str, model_hash: str
    ) -> tuple[list[str], list[str], str | None]:
        """Замыкающая миграция: операторы, откат и предусловие на хеш прежней версии."""
        ...

    def baseline_statements(self, descriptor: Descriptor) -> list[str]:
        """Полная схема модели — свёртка, а не история изменений."""
        ...


class Clock(Protocol):
    """Источник метки времени выпуска."""

    def now(self) -> datetime: ...


class ModelSource(Protocol):
    """Модель рабочего каталога: объекты модели и нарушения формата её файлов."""

    def read(self) -> ModelReading: ...


class ReleasedDescriptors(Protocol):
    """Последний выпущенный дескриптор старшего разряда; `None` — выпусков ещё не было."""

    def latest(self, major: int) -> Descriptor | None: ...


class MigrationNames(Protocol):
    """Имена файлов, уже лежащих в каталоге миграций: их метки времени заняты."""

    def taken(self, folder: str) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """Расхождение: место — файл и строка — и что с ним не так."""

    place: str
    message: str


def discrepancies(findings: Iterable[Finding]) -> tuple[Discrepancy, ...]:
    """Перевести нарушения домена в расхождения выходного контракта."""
    return tuple(
        Discrepancy(str(finding.place), f"{finding.element}: {finding.message}")
        for finding in findings
    )
