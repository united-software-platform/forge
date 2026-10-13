"""Состояния намерения и машина переходов между ними.

Состояние — свойство намерения, а не модели, и меняется только разрешённым переходом.
Переход, таблицей не предусмотренный, — ошибка процесса, а не молчаливое присваивание:
незамеченный переход означал бы, что цикл прошёл ветвь, которой в схеме нет.
"""

from __future__ import annotations

from enum import Enum

from ..errors import ModelError
from .step import Stage


class State(Enum):
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
        return _TITLES[self]


_TITLES = {
    State.DRAFT: "Черновик",
    State.VALIDATED: "Валидировано",
    State.IMPLEMENTED: "Реализовано",
    State.RELEASED: "Выпущено",
    State.APPLIED: "Применено",
    State.CONFIRMED: "Подтверждено",
    State.REWORK: "Доработка",
    State.ABORTED: "Прервано",
}

#: В какое состояние переводит пройденная стадия. Стадия намерения состояния не меняет:
#: заявка принята к прогону, но ещё ничем не подтверждена.
ON_PASSED: dict[Stage, State] = {
    Stage.INTENT: State.DRAFT,
    Stage.VALIDATE: State.VALIDATED,
    Stage.IMPLEMENT: State.IMPLEMENTED,
    Stage.GENERATE: State.RELEASED,
    Stage.APPLY: State.APPLIED,
    Stage.RECONCILE: State.CONFIRMED,
}

_PROGRESS = (
    (State.DRAFT, State.VALIDATED),
    (State.VALIDATED, State.IMPLEMENTED),
    (State.IMPLEMENTED, State.RELEASED),
    (State.RELEASED, State.APPLIED),
    (State.APPLIED, State.CONFIRMED),
)

#: Состояния, из которых стадия может отклонить намерение. Схема цикла рисует только два
#: обратных ребра — от валидации и от сверки, — но отклонить вправе любая стадия, поэтому
#: разрешены все рабочие состояния. Перечень схемы при этом целиком входит в таблицу.
_REWORK_FROM = (
    State.DRAFT,
    State.VALIDATED,
    State.IMPLEMENTED,
    State.RELEASED,
    State.APPLIED,
)

#: Разрешённые переходы: прямой ход по стадиям, уход в доработку и два выхода из неё —
#: следующая итерация и прерывание по исчерпании лимита.
TRANSITIONS: frozenset[tuple[State, State]] = frozenset(
    [
        *_PROGRESS,
        *((state, State.REWORK) for state in _REWORK_FROM),
        (State.REWORK, State.DRAFT),
        (State.REWORK, State.ABORTED),
    ]
)


def advance(state: State, target: State) -> State:
    """Перевести намерение в целевое состояние, если переход разрешён."""
    if state is target:
        return state
    if (state, target) not in TRANSITIONS:
        raise ModelError(
            f"переход {state.title} → {target.title} машиной состояний не предусмотрен",
            where="цикл намерения",
        )
    return target
