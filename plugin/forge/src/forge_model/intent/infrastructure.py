"""Адаптеры цикла намерения: сценарий прогона в YAML, подставные шаги, отчёты прогонов в JSON.

Подставные шаги предметной работы не выполняют — ни чтения модели, ни выпуска миграций,
ни обращения к хранилищу. Их назначение одно: дать циклу исход, которым сценарий прогона
описывает проверяемую ветвь. Предметный шаг встаёт на место подставного за тем же контрактом.

Нумерация итераций ведётся по уже записанным отчётам: засчитываются только итерации,
ушедшие в доработку, — отчёт останова описывает ту же итерацию, и следующий прогон
продолжает её, а не открывает новую.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

import yaml

from ..errors import EnvironmentFault
from .application.contracts import (
    Discrepancy,
    ScenarioReading,
    Step,
    StepContext,
    StepResult,
    Steps,
)
from .domain import STAGES, IterationReport, RunScenario, Stage, StageOutcome, Verdict

CODE_RE: Final = re.compile(r"^INT-[0-9]{3}$")

_ALLOWED_KEYS: Final = {"intent", "positions", "stages"}
_STAGES_BY_KEY: Final = {stage.value: stage for stage in Stage}
_OUTCOMES_BY_KEY: Final = {outcome.value: outcome for outcome in StageOutcome}

#: Вердикт, которым подставная сверка отвечает на свой исход. Вердикт здесь не вычисляется:
#: подставная сверка возвращает его механически, а разбирать его цикл и не должен.
_VERDICTS: Final = {
    StageOutcome.PASSED: "Исполнено",
    StageOutcome.REJECTED: "Не исполнено",
    StageOutcome.HALTED: "Не исполнено",
    StageOutcome.FAILED: "Не исполнено",
}


class _Invalid(Exception):  # noqa: N818 — внутренний сигнал разбора, наружу не выходит
    """Сценарий не того вида: причина отказа и стадия, к которой она относится."""

    def __init__(self, message: str, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage


class YamlScenarioSource:
    """Реализация `ScenarioSource` над файлом сценария в YAML."""

    def read(self, path: Path) -> ScenarioReading:
        where = f"сценарий {path}"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise EnvironmentFault("файл не найден", where=where) from error
        except yaml.YAMLError as error:
            return _rejected(where, f"файл не читается как YAML: {error}")
        try:
            return ScenarioReading(_scenario(raw))
        except _Invalid as invalid:
            place = where if invalid.stage is None else f"{where}, стадия {invalid.stage}"
            return _rejected(place, str(invalid))


def _rejected(where: str, message: str) -> ScenarioReading:
    return ScenarioReading(None, (Discrepancy(where, message),))


def _scenario(raw: Any) -> RunScenario:
    if not isinstance(raw, dict):
        raise _Invalid("сценарий должен быть отображением ключей")
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise _Invalid(f"неизвестные ключи: {', '.join(unknown)}")
    return RunScenario(
        code=_code(raw.get("intent")),
        positions=_positions(raw.get("positions")),
        outcomes=_outcomes(raw.get("stages")),
    )


def _code(raw: Any) -> str:
    if not isinstance(raw, str) or not CODE_RE.match(raw):
        raise _Invalid(f"код намерения {raw!r} не имеет вида INT-001")
    return raw


def _positions(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise _Invalid("позиции должны быть перечнем строк")
    return tuple(raw)


def _outcomes(raw: Any) -> tuple[tuple[Stage, tuple[StageOutcome, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise _Invalid("исходы стадий должны быть отображением стадий")
    outcomes: list[tuple[Stage, tuple[StageOutcome, ...]]] = []
    for key, value in raw.items():
        stage = _STAGES_BY_KEY.get(key)
        if stage is None:
            known = ", ".join(_STAGES_BY_KEY)
            raise _Invalid(f"неизвестная стадия {key!r}; известны: {known}")
        outcomes.append((stage, _planned(value, key)))
    return tuple(outcomes)


def _planned(raw: Any, key: str) -> tuple[StageOutcome, ...]:
    values = raw if isinstance(raw, list) else [raw]
    if not values:
        raise _Invalid("перечень исходов пуст", key)
    planned: list[StageOutcome] = []
    for item in values:
        outcome = _OUTCOMES_BY_KEY.get(item) if isinstance(item, str) else None
        if outcome is None:
            known = ", ".join(_OUTCOMES_BY_KEY)
            raise _Invalid(f"неизвестный исход {item!r}; известны: {known}", key)
        planned.append(outcome)
    return tuple(planned)


class ScenarioSteps:
    """Реализация `StepsFactory`: подставные шаги, исход которых берётся из сценария прогона."""

    def steps(self, scenario: RunScenario) -> Steps:
        return {stage: _step(stage, scenario) for stage in STAGES}


def _step(stage: Stage, scenario: RunScenario) -> Step:
    def run(context: StepContext) -> StepResult:
        outcome = scenario.outcome_for(stage, context.iteration)
        return StepResult(
            outcome=outcome,
            message="исход задан сценарием",
            verdicts=_verdicts(stage, outcome, context),
        )

    return run


def _verdicts(stage: Stage, outcome: StageOutcome, context: StepContext) -> tuple[Verdict, ...]:
    if stage is not Stage.RECONCILE:
        return ()
    return tuple(Verdict(position, _VERDICTS[outcome]) for position in context.positions)


class FileRunHistory:
    """Реализация `RunHistory` над каталогом отчётов прогонов."""

    def __init__(self, runs: Path) -> None:
        self._runs = runs

    def next_iteration(self, code: str) -> int:
        target = self._runs / code
        if not target.is_dir():
            return 1
        numbers = [report["iteration"] for report in _stored(target) if report.get("counted")]
        return max(numbers, default=0) + 1


def _stored(target: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Чужой или испорченный файл в каталоге отчётов не должен ронять прогон:
            # нумерация ведётся по тем отчётам, которые читаются.
            continue
        if isinstance(payload, dict) and isinstance(payload.get("iteration"), int):
            reports.append(payload)
    return reports


class FileRunReports:
    """Реализация `RunReports`: отчёт итерации — файл `<код>/<итерация>.json`."""

    def __init__(self, runs: Path) -> None:
        self._runs = runs

    def write(self, report: IterationReport) -> Path:
        target = self._runs / report.code
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{report.iteration}.json"
        path.write_text(
            json.dumps(_payload(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


def _payload(report: IterationReport) -> dict[str, object]:
    """Машиночитаемое представление отчёта."""
    return {
        "intent": report.code,
        "iteration": report.iteration,
        "counted": report.counted,
        "state": report.state.value,
        "state_title": report.state.title,
        "reason": report.reason,
        "stages": [
            {"stage": stage.value, "outcome": outcome.value} for stage, outcome in report.stages
        ],
        "verdicts": [
            {"position": verdict.position, "verdict": verdict.verdict}
            for verdict in report.verdicts
        ],
    }
