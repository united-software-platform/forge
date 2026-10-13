"""Сценарий `forge intent run`: провести намерение через замкнутый цикл.

Один вызов проводит намерение через весь цикл: из доработки сценарий открывает следующую
итерацию сам и останавливается подтверждением, прерыванием по лимиту либо штатным остановом,
когда стадия ждёт работы вне цикла. Отчёт пишется при любом исходе, включая ошибку процесса:
незаписанный отчёт означал бы, что последний вердикт цикла нигде не зафиксирован.

Ошибка процесса цикла — исход со своим кодом `2`, а не исключение: слой приложения не зависит
от исключения окружения, а для входа исход отличим от незамкнутого цикла ровно так же.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Protocol

from ..domain import (
    ON_PASSED,
    STAGES,
    IntentState,
    IterationReport,
    RunScenario,
    Stage,
    StageOutcome,
    TransitionRefused,
    Verdict,
    advance,
)
from .contracts import (
    CLOSED,
    NOT_CLOSED,
    PROCESS_ERROR,
    REJECTED,
    Discrepancy,
    RunHistory,
    RunReports,
    ScenarioSource,
    StepContext,
    StepResult,
    Steps,
    StepsFactory,
)

#: Лимит итераций по умолчанию. Значение задаётся снаружи цикла: без лимита прогон
#: на систематически отрицательном вердикте крутится бесконечно.
DEFAULT_MAX_ITERATIONS: Final = 3

#: Место нарушений, относящихся к циклу целиком, а не к одной стадии.
CYCLE: Final = "цикл намерения"


@dataclass(frozen=True, slots=True)
class RunIntentInput:
    """Файл сценария прогона и лимит итераций."""

    scenario: Path
    max_iterations: int = DEFAULT_MAX_ITERATIONS


@dataclass(frozen=True, slots=True)
class RunIntentOutput:
    """Исход прогона, конечное состояние, засчитанные итерации, отчёты, сводка, расхождения.

    Состояние передаётся значением перечня (`confirmed`, `aborted` и т. д.), а не объектом домена.
    """

    outcome: str
    state: str = ""
    iterations: int = 0
    reports: tuple[Path, ...] = ()
    summary: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class RunIntentUseCaseInterface(Protocol):
    """Контракт сценария прогона цикла: от него зависит вход ядра."""

    def execute(self, request: RunIntentInput) -> RunIntentOutput: ...


class RunIntentUseCase:
    """Реализация `RunIntentUseCaseInterface`."""

    def __init__(
        self,
        scenarios: ScenarioSource,
        steps: StepsFactory,
        history: RunHistory,
        reports: RunReports,
    ) -> None:
        self._scenarios = scenarios
        self._steps = steps
        self._history = history
        self._reports = reports

    def execute(self, request: RunIntentInput) -> RunIntentOutput:
        reading = self._scenarios.read(request.scenario)
        if reading.scenario is None:
            return RunIntentOutput(REJECTED, discrepancies=reading.problems)
        if request.max_iterations < 1:
            return _fault(CYCLE, f"лимит итераций {request.max_iterations} меньше одной")
        steps = self._steps.steps(reading.scenario)
        missing = [stage.value for stage in STAGES if stage not in steps]
        if missing:
            # Проверка до первой стадии: дыра в наборе иначе всплыла бы отчётом с половиной
            # выполненных стадий, и причину пришлось бы искать по нему.
            return _fault(CYCLE, f"в наборе нет шагов для стадий: {', '.join(missing)}")
        try:
            return self._cycle(reading.scenario, steps, request.max_iterations)
        except TransitionRefused as refused:
            return _fault(CYCLE, str(refused))

    def _cycle(self, scenario: RunScenario, steps: Steps, limit: int) -> RunIntentOutput:
        iteration = self._history.next_iteration(scenario.code)
        written: list[Path] = []
        counted = 0
        while True:
            report, fault = _iterate(scenario, steps, iteration)
            if fault is not None:
                self._reports.write(report)
                return RunIntentOutput(PROCESS_ERROR, discrepancies=(fault,))
            written.append(self._reports.write(report))
            if report.state is not IntentState.REWORK:
                return _finished(report, counted, written)

            counted += 1
            if iteration >= limit:
                aborted = replace(
                    report,
                    state=advance(report.state, IntentState.ABORTED),
                    reason=f"лимит итераций исчерпан: выполнено {iteration} из {limit}",
                )
                written[-1] = self._reports.write(aborted)
                return _finished(aborted, counted, written)

            # Доработка при неисчерпанном лимите открывает следующую итерацию: состояние
            # возвращается в черновик, и цикл начинается с первой стадии.
            advance(report.state, IntentState.DRAFT)
            iteration += 1


def _iterate(
    scenario: RunScenario, steps: Steps, iteration: int
) -> tuple[IterationReport, Discrepancy | None]:
    """Одна итерация: стадии по порядку до первого исхода, отличного от «пройдено»."""
    context = StepContext(scenario.code, scenario.positions, iteration)
    state, reason = IntentState.DRAFT, "цикл замкнут: намерение подтверждено"
    stages: list[tuple[Stage, StageOutcome]] = []
    verdicts: tuple[Verdict, ...] = ()

    def report() -> IterationReport:
        return IterationReport(scenario.code, iteration, state, reason, tuple(stages), verdicts)

    for stage in STAGES:
        result = steps[stage](context)
        problem = _malformed(result)
        if problem is not None:
            reason = f"ошибка процесса на стадии {stage.title}"
            return report(), Discrepancy(f"стадия {stage.value}", problem)

        stages.append((stage, result.outcome))
        if result.verdicts:
            verdicts = result.verdicts
        if result.outcome is StageOutcome.PASSED:
            state = advance(state, ON_PASSED[stage])
            continue
        if result.outcome is StageOutcome.REJECTED:
            state = advance(state, IntentState.REWORK)
            reason = f"отклонено на стадии {stage.title}: {result.message}"
            break
        if result.outcome is StageOutcome.HALTED:
            reason = f"останов на стадии {stage.title}: {result.message}"
            break

        reason = f"ошибка процесса на стадии {stage.title}: {result.message}"
        failure = result.message or "шаг сообщил об ошибке"
        return report(), Discrepancy(f"стадия {stage.value}", failure)

    return report(), None


def _malformed(value: object) -> str | None:
    """Что не так с результатом шага; `None` — результат известной формы с известным исходом."""
    if not isinstance(value, StepResult):
        return f"шаг вернул {value!r} вместо результата шага"
    if not isinstance(value.outcome, StageOutcome):
        return f"шаг вернул неизвестный исход {value.outcome!r}"
    return None


def _finished(report: IterationReport, counted: int, written: list[Path]) -> RunIntentOutput:
    closed = report.state is IntentState.CONFIRMED
    return RunIntentOutput(
        CLOSED if closed else NOT_CLOSED,
        state=report.state.value,
        iterations=counted,
        reports=tuple(written),
        summary=(
            f"{report.code}  {report.state.title}: {report.reason}",
            f"итераций засчитано: {counted}",
            *(f"отчёт: {path}" for path in written),
        ),
    )


def _fault(place: str, message: str) -> RunIntentOutput:
    return RunIntentOutput(PROCESS_ERROR, discrepancies=(Discrepancy(place, message),))
