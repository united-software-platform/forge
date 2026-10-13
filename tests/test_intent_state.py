"""Машина состояний: перечень, таблица переходов, отказ на неразрешённом переходе."""

import pytest
from forge_model.intent.domain import TRANSITIONS, IntentState, TransitionRefused, advance

#: Рёбра диаграммы состояний из документа цикла. Таблица переходов обязана содержать
#: их все; сверх них она разрешает уход в доработку из прочих рабочих состояний.
DIAGRAM = [
    (IntentState.DRAFT, IntentState.VALIDATED),
    (IntentState.DRAFT, IntentState.REWORK),
    (IntentState.VALIDATED, IntentState.IMPLEMENTED),
    (IntentState.IMPLEMENTED, IntentState.RELEASED),
    (IntentState.RELEASED, IntentState.APPLIED),
    (IntentState.APPLIED, IntentState.CONFIRMED),
    (IntentState.APPLIED, IntentState.REWORK),
    (IntentState.REWORK, IntentState.DRAFT),
    (IntentState.REWORK, IntentState.ABORTED),
]


def test_state_list_is_closed():
    """Перечень состояний закрыт восемью значениями схемы."""
    assert [state.title for state in IntentState] == [
        "Черновик",
        "Валидировано",
        "Реализовано",
        "Выпущено",
        "Применено",
        "Подтверждено",
        "Доработка",
        "Прервано",
    ]


@pytest.mark.parametrize(("source", "target"), DIAGRAM)
def test_diagram_edge_is_allowed(source, target):
    """Каждое ребро диаграммы документа разрешено таблицей переходов."""
    assert advance(source, target) is target


@pytest.mark.parametrize("final", [IntentState.CONFIRMED, IntentState.ABORTED])
def test_final_state_has_no_exit(final):
    """Из конечных состояний переходов нет: цикл на них завершается."""
    assert not [pair for pair in TRANSITIONS if pair[0] is final]


def test_forbidden_transition_is_process_error():
    """Неразрешённый переход даёт ошибку с указанием обоих состояний."""
    with pytest.raises(TransitionRefused, match="Черновик → Подтверждено"):
        advance(IntentState.DRAFT, IntentState.CONFIRMED)


def test_same_state_is_not_a_transition():
    """Стадия, состояния не меняющая, переходом не считается."""
    assert advance(IntentState.DRAFT, IntentState.DRAFT) is IntentState.DRAFT


def test_successful_pass_walks_every_state():
    """Успешный проход ведёт от черновика к подтверждению без пропусков."""
    order = [
        IntentState.DRAFT,
        IntentState.VALIDATED,
        IntentState.IMPLEMENTED,
        IntentState.RELEASED,
        IntentState.APPLIED,
        IntentState.CONFIRMED,
    ]
    state = order[0]
    for target in order[1:]:
        state = advance(state, target)
    assert state is IntentState.CONFIRMED
