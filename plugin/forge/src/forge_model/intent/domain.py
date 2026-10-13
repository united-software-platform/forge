"""Домен цикла намерения: стадии, исходы стадий, состояния намерения, отчёт итерации.

Состояние — свойство намерения, а не модели, и меняется только разрешённым переходом.
Переход, таблицей не предусмотренный, — ошибка процесса, а не молчаливое присваивание:
незамеченный переход означал бы, что цикл прошёл ветвь, которой в схеме нет.

Сценарий прогона — единственный источник решений подставных шагов; он же задаёт вход
цикла: предметного чтения заявки в составе цикла нет, а вердикты в отчёте должны к чему-то
относиться (design D8 change `layer-forge-core`).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final


class Stage(enum.Enum):
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


_STAGE_TITLES: Final = {
    Stage.INTENT: "намерение",
    Stage.VALIDATE: "валидация",
    Stage.IMPLEMENT: "реализация модели",
    Stage.GENERATE: "преобразование в миграцию",
    Stage.APPLY: "накат",
    Stage.RECONCILE: "сверка с фактом",
}

#: Стадии в порядке выполнения. Порядок задан объявлением и параметрами не меняется.
STAGES: Final[tuple[Stage, ...]] = tuple(Stage)


class StageOutcome(enum.Enum):
    """Исход стадии. Каждому значению отвечает своё ребро схемы цикла."""

    PASSED = "passed"
    REJECTED = "rejected"
    HALTED = "halted"
    FAILED = "failed"

    @property
    def title(self) -> str:
        """Название исхода для вывода."""
        return _OUTCOME_TITLES[self]


_OUTCOME_TITLES: Final = {
    StageOutcome.PASSED: "пройдено",
    StageOutcome.REJECTED: "отклонено",
    StageOutcome.HALTED: "остановлено",
    StageOutcome.FAILED: "ошибка",
}


@dataclass(frozen=True)
class Verdict:
    """Вердикт по одной позиции намерения.

    Текст вердикта цикл не разбирает и не вычисляет: он переносит его из результата шага
    в отчёт. Перечень вердиктов задаёт стадия сверки, а не оркестрация.
    """

    position: str
    verdict: str


class IntentState(enum.Enum):
    """Состояние намерения. Перечень закрыт схемой цикла."""

    DRAFT = "draft"
    VALIDATED = "validated"
    IMPLEMENTED = "implemented"
    RELEASED = "released"
    APPLIED = "applied"
    CONFIRMED = "confirmed"
    REWORK = "rework"
    ABORTED = "aborted"

    @property
    def title(self) -> str:
        """Название состояния для вывода."""
        return _STATE_TITLES[self]


_STATE_TITLES: Final = {
    IntentState.DRAFT: "Черновик",
    IntentState.VALIDATED: "Валидировано",
    IntentState.IMPLEMENTED: "Реализовано",
    IntentState.RELEASED: "Выпущено",
    IntentState.APPLIED: "Применено",
    IntentState.CONFIRMED: "Подтверждено",
    IntentState.REWORK: "Доработка",
    IntentState.ABORTED: "Прервано",
}

#: В какое состояние переводит пройденная стадия. Стадия намерения состояния не меняет:
#: заявка принята к прогону, но ещё ничем не подтверждена.
ON_PASSED: Final[Mapping[Stage, IntentState]] = {
    Stage.INTENT: IntentState.DRAFT,
    Stage.VALIDATE: IntentState.VALIDATED,
    Stage.IMPLEMENT: IntentState.IMPLEMENTED,
    Stage.GENERATE: IntentState.RELEASED,
    Stage.APPLY: IntentState.APPLIED,
    Stage.RECONCILE: IntentState.CONFIRMED,
}

_PROGRESS: Final = (
    (IntentState.DRAFT, IntentState.VALIDATED),
    (IntentState.VALIDATED, IntentState.IMPLEMENTED),
    (IntentState.IMPLEMENTED, IntentState.RELEASED),
    (IntentState.RELEASED, IntentState.APPLIED),
    (IntentState.APPLIED, IntentState.CONFIRMED),
)

#: Состояния, из которых стадия может отклонить намерение. Схема цикла рисует только два
#: обратных ребра — от валидации и от сверки, — но отклонить вправе любая стадия, поэтому
#: разрешены все рабочие состояния. Перечень схемы при этом целиком входит в таблицу.
_REWORK_FROM: Final = (
    IntentState.DRAFT,
    IntentState.VALIDATED,
    IntentState.IMPLEMENTED,
    IntentState.RELEASED,
    IntentState.APPLIED,
)

#: Разрешённые переходы: прямой ход по стадиям, уход в доработку и два выхода из неё —
#: следующая итерация и прерывание по исчерпании лимита.
TRANSITIONS: Final[frozenset[tuple[IntentState, IntentState]]] = frozenset(
    [
        *_PROGRESS,
        *((state, IntentState.REWORK) for state in _REWORK_FROM),
        (IntentState.REWORK, IntentState.DRAFT),
        (IntentState.REWORK, IntentState.ABORTED),
    ]
)


class TransitionRefused(Exception):  # noqa: N818 — нарушение правила домена, а не сбой
    """Переход, машиной состояний не предусмотренный: ошибка процесса цикла."""


def advance(state: IntentState, target: IntentState) -> IntentState:
    """Перевести намерение в целевое состояние, если переход разрешён."""
    if state is target:
        return state
    if (state, target) not in TRANSITIONS:
        raise TransitionRefused(
            f"переход {state.title} → {target.title} машиной состояний не предусмотрен"
        )
    return target


@dataclass(frozen=True)
class IterationReport:
    """Отчёт одной итерации цикла: намерение, состояние, исходы стадий, вердикты, причина."""

    code: str
    iteration: int
    state: IntentState
    reason: str
    stages: tuple[tuple[Stage, StageOutcome], ...] = ()
    verdicts: tuple[Verdict, ...] = ()

    @property
    def counted(self) -> bool:
        """Засчитана ли итерация в лимит.

        Засчитывается только уход в доработку — состоявшийся или прерванный лимитом.
        Останов и повторный прогон подтверждённого намерения номер итерации не двигают,
        иначе лимит выгорал бы на прогонах, в которых ничего не проверялось повторно.
        """
        return self.state in (IntentState.REWORK, IntentState.ABORTED)


@dataclass(frozen=True)
class RunScenario:
    """Сценарий прогона: код намерения, позиции и исходы стадий по итерациям."""

    code: str
    positions: tuple[str, ...] = ()
    outcomes: tuple[tuple[Stage, tuple[StageOutcome, ...]], ...] = ()

    def outcome_for(self, stage: Stage, iteration: int) -> StageOutcome:
        """Исход стадии на указанной итерации.

        Стадия, сценарием не названная, считается пройденной: описывать надо отклонение,
        а не норму. Список короче числа итераций повторяет последнее значение — так
        исчерпание лимита описывается одним значением.
        """
        planned = dict(self.outcomes).get(stage)
        if not planned:
            return StageOutcome.PASSED
        return planned[min(iteration, len(planned)) - 1]
