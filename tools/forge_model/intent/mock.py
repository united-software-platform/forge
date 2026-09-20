"""Подставные шаги стадий: исход берётся из сценария прогона.

Предметной работы шаги не выполняют — ни чтения модели, ни выпуска миграций,
ни обращения к хранилищу. Их назначение одно: дать движку исход, которым описана
проверяемая ветвь цикла.
"""

from __future__ import annotations

from .scenario import Scenario
from .step import STAGES, Outcome, Stage, Step, StepContext, StepResult, Steps, Verdict

#: Вердикт, которым стадия сверки отвечает на свой исход. Вердикт здесь не вычисляется:
#: подставная сверка возвращает его механически, а разбирать его движок и не должен.
_VERDICTS = {
    Outcome.PASSED: "Исполнено",
    Outcome.REJECTED: "Не исполнено",
    Outcome.HALTED: "Не исполнено",
    Outcome.FAILED: "Не исполнено",
}


def steps_for(scenario: Scenario) -> Steps:
    """Собрать набор подставных шагов на все стадии цикла."""
    return {stage: _step(stage, scenario) for stage in STAGES}


def _step(stage: Stage, scenario: Scenario) -> Step:
    def run(context: StepContext) -> StepResult:
        outcome = scenario.outcome_for(stage, context.iteration)
        return StepResult(
            outcome=outcome,
            message="исход задан сценарием",
            verdicts=_verdicts(stage, outcome, context),
        )

    return run


def _verdicts(stage: Stage, outcome: Outcome, context: StepContext) -> tuple[Verdict, ...]:
    if stage is not Stage.RECONCILE:
        return ()
    return tuple(Verdict(position, _VERDICTS[outcome]) for position in context.positions)
