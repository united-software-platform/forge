"""Контракты чтения модуля контракта модели, модель расхождения и исходы его сценариев.

Контракты узкие и отвечают каждый на один вопрос (APB-005 (2)): какая модель лежит
в рабочем каталоге и какой дескриптор выпущен последним. Реализации — в инфраструктуре;
сценарий зависит только от контракта.

Расхождение — данные слоя приложения, а не доменное нарушение: выходной контракт сценария
не несёт объектов домена. Форма расхождения одна во всех модулях ядра, но объявлена в каждом
модуле своя: слой приложения одного модуля не импортирует слой приложения другого.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Protocol

from ..domain import Descriptor, Finding, ModelReading

#: Исходы сценариев модуля.
BUILT: Final = "built"
COMPARED: Final = "compared"
NOTHING_TO_RELEASE: Final = "nothing_to_release"
REJECTED: Final = "rejected"


class ModelSource(Protocol):
    """Модель рабочего каталога: объекты модели и нарушения формата её файлов."""

    def read(self) -> ModelReading: ...


class ReleasedDescriptors(Protocol):
    """Последний выпущенный дескриптор старшего разряда; `None` — выпусков ещё не было."""

    def latest(self, major: int) -> Descriptor | None: ...


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
