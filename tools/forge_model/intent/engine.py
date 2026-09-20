"""Движок цикла: стадии, итерации, лимит.

Один вызов проводит намерение через весь цикл: из доработки движок открывает следующую
итерацию сам и останавливается либо подтверждением, либо прерыванием по лимиту, либо
штатным остановом, когда стадия ждёт работы вне цикла.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import ModelError
from . import report as reports
from .report import IterationReport
from .scenario import Scenario
from .state import ON_PASSED, State, advance
from .step import STAGES, Outcome, StepContext, Steps, require_complete, require_result

#: Лимит итераций по умолчанию. Значение задаётся снаружи цикла: без лимита прогон
#: на систематически отрицательном вердикте крутится бесконечно.
DEFAULT_MAX_ITERATIONS = 3


@dataclass(frozen=True)
class RunOutcome:
    """Итог прогона целиком."""

    code: str
    state: State
    iterations: int
    reason: str
    reports: tuple[Path, ...]

    @property
    def closed(self) -> bool:
        """Замкнулся ли цикл подтверждением."""
        return self.state is State.CONFIRMED


def run_cycle(
    scenario: Scenario,
    steps: Steps,
    *,
    runs_dir: Path,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> RunOutcome:
    """Прогнать цикл намерения до подтверждения, останова или прерывания."""
    if max_iterations < 1:
        raise ModelError(f"лимит итераций {max_iterations} меньше одной", where="цикл намерения")
    require_complete(steps)

    iteration = reports.next_iteration(runs_dir, scenario.code)
    written: list[Path] = []
    counted = 0

    while True:
        report = _iterate(scenario, steps, iteration=iteration, runs_dir=runs_dir)
        written.append(reports.write(runs_dir, report))

        if report.state is not State.REWORK:
            return RunOutcome(scenario.code, report.state, counted, report.reason, tuple(written))

        counted += 1
        if iteration >= max_iterations:
            report.state = advance(report.state, State.ABORTED)
            report.reason = f"лимит итераций исчерпан: выполнено {iteration} из {max_iterations}"
            written[-1] = reports.write(runs_dir, report)
            return RunOutcome(scenario.code, report.state, counted, report.reason, tuple(written))

        # Доработка при неисчерпанном лимите открывает следующую итерацию: состояние
        # возвращается в черновик, и цикл начинается с первой стадии.
        advance(report.state, State.DRAFT)
        iteration += 1


def _iterate(
    scenario: Scenario, steps: Steps, *, iteration: int, runs_dir: Path
) -> IterationReport:
    """Провести одну итерацию: стадии по порядку до первого исхода, отличного от «пройдено»."""
    context = StepContext(scenario.code, scenario.positions, iteration)
    report = IterationReport(
        code=scenario.code,
        iteration=iteration,
        state=State.DRAFT,
        reason="цикл замкнут: намерение подтверждено",
    )

    for stage in STAGES:
        try:
            result = require_result(stage, steps[stage](context))
        except ModelError:
            report.reason = f"ошибка процесса на стадии {stage.title}"
            reports.write(runs_dir, report)
            raise

        report.stages.append((stage, result.outcome))
        if result.verdicts:
            report.verdicts = result.verdicts

        if result.outcome is Outcome.PASSED:
            report.state = advance(report.state, ON_PASSED[stage])
            continue
        if result.outcome is Outcome.REJECTED:
            report.state = advance(report.state, State.REWORK)
            report.reason = f"отклонено на стадии {stage.title}: {result.message}"
            break
        if result.outcome is Outcome.HALTED:
            report.reason = f"останов на стадии {stage.title}: {result.message}"
            break

        report.reason = f"ошибка процесса на стадии {stage.title}: {result.message}"
        reports.write(runs_dir, report)
        raise ModelError(result.message or "шаг сообщил об ошибке", where=f"стадия {stage.value}")

    return report
