"""Контракт шага: форма результата, полнота набора, неизвестный исход."""

import pytest
from forge_model.errors import ModelError
from forge_model.intent.step import (
    STAGES,
    Outcome,
    Stage,
    StepContext,
    StepResult,
    Steps,
    Verdict,
    require_complete,
    require_result,
)


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


@pytest.mark.parametrize("outcome", list(Outcome))
def test_result_of_every_outcome(outcome):
    """Результат строится на любом из четырёх исходов."""
    result = StepResult(outcome=outcome, message="повод", verdicts=(Verdict("поле", "Исполнено"),))
    assert result.outcome is outcome
    assert result.verdicts[0].position == "поле"


def test_result_defaults_to_empty_verdicts():
    """Стадия, вердиктов не дающая, возвращает результат без них."""
    assert StepResult(outcome=Outcome.PASSED).verdicts == ()


def test_complete_set_passes():
    """Набор на все стадии проверку проходит."""
    require_complete(dict.fromkeys(STAGES, _step))


def test_incomplete_set_is_process_error():
    """Неполный набор отвергается до выполнения первой стадии."""
    partial: Steps = {stage: _step for stage in STAGES if stage is not Stage.APPLY}
    with pytest.raises(ModelError, match="apply"):
        require_complete(partial)


def test_unknown_outcome_is_process_error():
    """Исход вне перечня завершает прогон ошибкой с указанием стадии."""
    broken = StepResult.__new__(StepResult)
    object.__setattr__(broken, "outcome", "готово")
    object.__setattr__(broken, "message", "")
    object.__setattr__(broken, "verdicts", ())
    with pytest.raises(ModelError, match=r"стадия validate.*готово"):
        require_result(Stage.VALIDATE, broken)


def test_foreign_result_is_process_error():
    """Шаг, вернувший не результат шага, тоже даёт ошибку процесса."""
    with pytest.raises(ModelError, match="стадия intent"):
        require_result(Stage.INTENT, "пройдено")


def _step(context: StepContext) -> StepResult:
    return StepResult(outcome=Outcome.PASSED, message=context.code)
