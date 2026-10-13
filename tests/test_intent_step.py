"""Контракт шага: форма результата, полнота набора, неизвестный исход."""

from typing import Any

import pytest
from forge_model.intent.application.contracts import (
    CLOSED,
    PROCESS_ERROR,
    StepContext,
    StepResult,
    Steps,
)
from forge_model.intent.domain import STAGES, RunScenario, Stage, StageOutcome, Verdict

from tests.conftest import run_intent

SCENARIO = RunScenario(code="INT-001", positions=("поле FR.code",))


def _fault(output):
    """Ошибка процесса цикла: место и сообщение расхождения одной строкой."""
    assert output.outcome == PROCESS_ERROR
    return " ".join(f"{item.place}: {item.message}" for item in output.discrepancies)


def test_stages_follow_cycle_order():
    """Порядок стадий задан объявлением и совпадает со схемой цикла."""
    assert [stage.value for stage in STAGES] == [
        "intent",
        "validate",
        "implement",
        "generate",
        "apply",
        "reconcile",
    ]


@pytest.mark.parametrize("outcome", list(StageOutcome))
def test_result_of_every_outcome(outcome):
    """Результат строится на любом из четырёх исходов."""
    result = StepResult(outcome=outcome, message="повод", verdicts=(Verdict("поле", "Исполнено"),))
    assert result.outcome is outcome
    assert result.verdicts[0].position == "поле"


def test_result_defaults_to_empty_verdicts():
    """Стадия, вердиктов не дающая, возвращает результат без них."""
    assert StepResult(outcome=StageOutcome.PASSED).verdicts == ()


def test_complete_set_passes(tmp_path):
    """Набор на все стадии проверку проходит."""
    assert run_intent(tmp_path, SCENARIO, dict.fromkeys(STAGES, _step)).outcome == CLOSED


def test_incomplete_set_is_process_error(tmp_path):
    """Неполный набор отвергается до выполнения первой стадии."""
    partial: Steps = {stage: _step for stage in STAGES if stage is not Stage.APPLY}

    assert "apply" in _fault(run_intent(tmp_path, SCENARIO, partial))


def test_unknown_outcome_is_process_error(tmp_path):
    """Исход вне перечня завершает прогон ошибкой с указанием стадии."""
    broken = StepResult.__new__(StepResult)
    object.__setattr__(broken, "outcome", "готово")
    object.__setattr__(broken, "message", "")
    object.__setattr__(broken, "verdicts", ())
    steps = {**dict.fromkeys(STAGES, _step), Stage.VALIDATE: lambda context: broken}

    message = _fault(run_intent(tmp_path, SCENARIO, steps))

    assert message.startswith("стадия validate:") and "готово" in message


def test_foreign_result_is_process_error(tmp_path):
    """Шаг, вернувший не результат шага, тоже даёт ошибку процесса."""
    # Шаг нарушает контракт намеренно: тип результата не тот.
    steps: dict[Stage, Any] = {**dict.fromkeys(STAGES, _step), Stage.INTENT: lambda c: "пройдено"}

    assert _fault(run_intent(tmp_path, SCENARIO, steps)).startswith("стадия intent:")


def _step(context: StepContext) -> StepResult:
    return StepResult(outcome=StageOutcome.PASSED, message=context.code)
