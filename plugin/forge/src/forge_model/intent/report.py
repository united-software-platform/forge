"""Отчёт прогона: состав, запись и нумерация итераций.

Отчёт пишется при любом исходе, включая ошибку процесса: незаписанный отчёт означал бы,
что последний вердикт цикла нигде не зафиксирован, а решение о продолжении принимается
именно по нему.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .state import State
from .step import Outcome, Stage, Verdict


@dataclass
class IterationReport:
    """Отчёт одной итерации цикла."""

    code: str
    iteration: int
    state: State
    reason: str
    stages: list[tuple[Stage, Outcome]] = field(default_factory=list)
    verdicts: tuple[Verdict, ...] = ()

    @property
    def counted(self) -> bool:
        """Засчитана ли итерация в лимит.

        Засчитывается только уход в доработку — состоявшийся или прерванный лимитом.
        Останов и повторный прогон подтверждённого намерения номер итерации не двигают,
        иначе лимит выгорал бы на прогонах, в которых ничего не проверялось повторно.
        """
        return self.state in (State.REWORK, State.ABORTED)

    def payload(self) -> dict[str, object]:
        """Машиночитаемое представление отчёта."""
        return {
            "intent": self.code,
            "iteration": self.iteration,
            "counted": self.counted,
            "state": self.state.value,
            "state_title": self.state.title,
            "reason": self.reason,
            "stages": [
                {"stage": stage.value, "outcome": outcome.value} for stage, outcome in self.stages
            ],
            "verdicts": [
                {"position": verdict.position, "verdict": verdict.verdict}
                for verdict in self.verdicts
            ],
        }


def write(runs_dir: Path, report: IterationReport) -> Path:
    """Записать отчёт итерации и вернуть путь к нему."""
    target = runs_dir / report.code
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{report.iteration}.json"
    path.write_text(
        json.dumps(report.payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def next_iteration(runs_dir: Path, code: str) -> int:
    """Номер следующей итерации по уже лежащим отчётам.

    Считаются только засчитанные итерации: отчёт останова описывает ту же итерацию,
    и следующий прогон продолжает её, а не открывает новую.
    """
    target = runs_dir / code
    if not target.is_dir():
        return 1
    numbers = [report["iteration"] for report in _stored(target) if report.get("counted")]
    return max(numbers, default=0) + 1


def _stored(target: Path) -> list[dict[str, int]]:
    reports: list[dict[str, int]] = []
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
