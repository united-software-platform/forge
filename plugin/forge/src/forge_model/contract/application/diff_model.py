"""Сценарий `forge diff`: сравнить рабочую модель с последней выпущенной версией.

Сравнение печатает то же решение гейта совместимости, что и выпуск: переход версий, операции
дельты с классами и предупреждения. Решение гейта «отвергнуто» — штатный исход с расхождениями,
выпуска сценарий не выполняет.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .. import domain
from ..domain import CompatibilityGate, compile_descriptor
from .contracts import (
    COMPARED,
    NOTHING_TO_RELEASE,
    REJECTED,
    Discrepancy,
    ModelSource,
    ReleasedDescriptors,
    discrepancies,
)


@dataclass(frozen=True, slots=True)
class DiffModelInput:
    """Сценарий параметров не принимает: обе версии читают источники."""


@dataclass(frozen=True, slots=True)
class DiffModelOutput:
    """Исход, сводка решения гейта для печати и расхождения отказа."""

    outcome: str
    summary: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class DiffModelUseCaseInterface(Protocol):
    """Контракт сценария сравнения версий: от него зависит вход ядра."""

    def execute(self, request: DiffModelInput) -> DiffModelOutput: ...


class DiffModelUseCase:
    """Реализация `DiffModelUseCaseInterface`."""

    def __init__(self, source: ModelSource, released: ReleasedDescriptors) -> None:
        self._source = source
        self._released = released

    def execute(self, request: DiffModelInput) -> DiffModelOutput:
        compilation = compile_descriptor(self._source.read())
        current = compilation.descriptor
        if current is None:
            return DiffModelOutput(REJECTED, discrepancies=discrepancies(compilation.findings))

        decision = CompatibilityGate().decide(current, self._released.latest(current.major))
        if decision.outcome == domain.REJECTED:
            return DiffModelOutput(REJECTED, discrepancies=discrepancies(decision.findings))
        outcome = NOTHING_TO_RELEASE if decision.outcome == domain.NOTHING_TO_RELEASE else COMPARED
        return DiffModelOutput(outcome, summary=decision.report())
