"""Контракт шага стадии: перечень стадий, исходы, результат и набор шагов.

Движок выбирает следующее действие только по исходу результата. О внутреннем
устройстве шага он не знает ничего, поэтому предметная реализация встаёт на место
подставной без правок оркестрации.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from ..errors import ModelError


class Stage(Enum):
    """Стадия цикла. Порядок объявления и есть порядок выполнения."""

    INTENT = "intent"
    VALIDATE = "validate"
    IMPLEMENT = "implement"
    GENERATE = "generate"
    APPLY = "apply"
    RECONCILE = "reconcile"

    @property
    def title(self) -> str:
        """Название стадии для вывода."""
        return _STAGE_TITLES[self]


_STAGE_TITLES = {
    Stage.INTENT: "намерение",
    Stage.VALIDATE: "валидация",
    Stage.IMPLEMENT: "реализация модели",
    Stage.GENERATE: "преобразование в миграцию",
    Stage.APPLY: "накат",
    Stage.RECONCILE: "сверка с фактом",
}

#: Стадии в порядке выполнения. Порядок задан объявлением и параметрами не меняется.
STAGES: tuple[Stage, ...] = tuple(Stage)


class Outcome(Enum):
    """Исход стадии. Каждому значению отвечает своё ребро схемы цикла."""

    PASSED = "passed"
    REJECTED = "rejected"
    HALTED = "halted"
    FAILED = "failed"

    @property
    def title(self) -> str:
        """Название исхода для вывода."""
        return _OUTCOME_TITLES[self]


_OUTCOME_TITLES = {
    Outcome.PASSED: "пройдено",
    Outcome.REJECTED: "отклонено",
    Outcome.HALTED: "остановлено",
    Outcome.FAILED: "ошибка",
}


@dataclass(frozen=True)
class Verdict:
    """Вердикт по одной позиции намерения.

    Текст вердикта движок не разбирает и не вычисляет: он переносит его из результата
    шага в отчёт. Перечень вердиктов задаёт стадия сверки, а не оркестрация.
    """

    position: str
    verdict: str


@dataclass(frozen=True)
class StepResult:
    """Результат шага единой формы: исход, сообщение и вердикты по позициям."""

    outcome: Outcome
    message: str = ""
    verdicts: tuple[Verdict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StepContext:
    """Что шаг знает о прогоне: намерение, его позиции и номер текущей итерации."""

    code: str
    positions: tuple[str, ...]
    iteration: int


#: Шаг стадии: получает контекст прогона, возвращает результат единой формы.
Step = Callable[[StepContext], StepResult]

#: Набор шагов на все стадии цикла.
Steps = Mapping[Stage, Step]


def require_complete(steps: Steps) -> None:
    """Проверить, что набор покрывает все стадии.

    Проверка выполняется до первой стадии: дыра в наборе иначе всплыла бы отчётом
    с половиной выполненных стадий, и причину пришлось бы искать по нему.
    """
    missing = [stage for stage in STAGES if stage not in steps]
    if missing:
        names = ", ".join(stage.value for stage in missing)
        raise ModelError(f"в наборе нет шагов для стадий: {names}", where="цикл намерения")


def require_result(stage: Stage, value: object) -> StepResult:
    """Проверить, что шаг вернул результат известной формы с известным исходом."""
    where = f"стадия {stage.value}"
    if not isinstance(value, StepResult):
        raise ModelError(f"шаг вернул {value!r} вместо результата шага", where=where)
    if not isinstance(value.outcome, Outcome):
        raise ModelError(f"шаг вернул неизвестный исход {value.outcome!r}", where=where)
    return value
