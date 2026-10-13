"""Контракты цикла намерения: шаг стадии, сценарий прогона, история и отчёты прогонов.

Цикл выбирает следующее действие только по исходу результата шага. О внутреннем устройстве
шага он не знает ничего, поэтому предметная реализация встаёт на место подставной без правок
оркестрации: набор шагов приходит извне, через контракт фабрики шагов.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from ..domain import IterationReport, RunScenario, Stage, StageOutcome, Verdict

#: Исходы прогона: цикл замкнут; не замкнут — останов или прерывание по лимиту; сценарий
#: отвергнут; ошибка процесса цикла.
CLOSED: Final = "closed"
NOT_CLOSED: Final = "not_closed"
REJECTED: Final = "rejected"
PROCESS_ERROR: Final = "process_error"


@dataclass(frozen=True, slots=True)
class StepContext:
    """Что шаг знает о прогоне: намерение, его позиции и номер текущей итерации."""

    code: str
    positions: tuple[str, ...]
    iteration: int


@dataclass(frozen=True, slots=True)
class StepResult:
    """Результат шага единой формы: исход, сообщение и вердикты по позициям."""

    outcome: StageOutcome
    message: str = ""
    verdicts: tuple[Verdict, ...] = ()


class Step(Protocol):
    """Шаг стадии: получает контекст прогона, возвращает результат единой формы."""

    def __call__(self, context: StepContext) -> StepResult: ...


#: Набор шагов на все стадии цикла.
Steps = Mapping[Stage, Step]


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """Расхождение: место — сценарий, стадия или цикл — и что с ним не так."""

    place: str
    message: str


@dataclass(frozen=True, slots=True)
class ScenarioReading:
    """Прочитанный сценарий прогона либо причина, по которой он отвергнут."""

    scenario: RunScenario | None
    problems: tuple[Discrepancy, ...] = ()


class ScenarioSource(Protocol):
    """Сценарий прогона из файла. Нет файла — ошибка окружения, а не отказ сценария."""

    def read(self, path: Path) -> ScenarioReading: ...


class StepsFactory(Protocol):
    """Набор шагов на все стадии цикла для сценария прогона."""

    def steps(self, scenario: RunScenario) -> Steps: ...


class RunHistory(Protocol):
    """Номер следующей итерации намерения по уже записанным отчётам."""

    def next_iteration(self, code: str) -> int: ...


class RunReports(Protocol):
    """Запись отчёта итерации; возвращает путь записанного отчёта."""

    def write(self, report: IterationReport) -> Path: ...
