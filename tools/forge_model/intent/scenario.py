"""Сценарий прогона: вход цикла и исходы стадий по итерациям.

Сценарий — единственный источник решений подставных шагов. Он же задаёт вход цикла:
предметного чтения заявки в составе движка нет, а вердикты в отчёте должны к чему-то
относиться.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..errors import ModelError
from .step import Outcome, Stage

CODE_RE = re.compile(r"^INT-[0-9]{3}$")

_ALLOWED_KEYS = {"intent", "positions", "stages"}
_STAGES_BY_KEY = {stage.value: stage for stage in Stage}
_OUTCOMES_BY_KEY = {outcome.value: outcome for outcome in Outcome}


@dataclass(frozen=True)
class Scenario:
    """Разобранный сценарий прогона."""

    code: str
    positions: tuple[str, ...]
    outcomes: dict[Stage, tuple[Outcome, ...]]

    def outcome_for(self, stage: Stage, iteration: int) -> Outcome:
        """Исход стадии на указанной итерации.

        Стадия, сценарием не названная, считается пройденной: описывать надо отклонение,
        а не норму. Список короче числа итераций повторяет последнее значение — так
        исчерпание лимита описывается одним значением.
        """
        planned = self.outcomes.get(stage)
        if not planned:
            return Outcome.PASSED
        return planned[min(iteration, len(planned)) - 1]


def load_scenario(path: Path) -> Scenario:
    """Прочитать сценарий прогона из файла."""
    where = f"сценарий {path}"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ModelError("файл не найден", where=where) from error
    except yaml.YAMLError as error:
        raise ModelError(f"файл не читается как YAML: {error}", where=where) from error

    if not isinstance(raw, dict):
        raise ModelError("сценарий должен быть отображением ключей", where=where)
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise ModelError(f"неизвестные ключи: {', '.join(unknown)}", where=where)

    return Scenario(
        code=_code(raw.get("intent"), where=where),
        positions=_positions(raw.get("positions"), where=where),
        outcomes=_outcomes(raw.get("stages"), where=where),
    )


def _code(raw: Any, *, where: str) -> str:
    if not isinstance(raw, str) or not CODE_RE.match(raw):
        raise ModelError(f"код намерения {raw!r} не имеет вида INT-001", where=where)
    return raw


def _positions(raw: Any, *, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ModelError("позиции должны быть перечнем строк", where=where)
    return tuple(raw)


def _outcomes(raw: Any, *, where: str) -> dict[Stage, tuple[Outcome, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ModelError("исходы стадий должны быть отображением стадий", where=where)

    outcomes: dict[Stage, tuple[Outcome, ...]] = {}
    for key, value in raw.items():
        stage = _STAGES_BY_KEY.get(key)
        if stage is None:
            known = ", ".join(_STAGES_BY_KEY)
            raise ModelError(f"неизвестная стадия {key!r}; известны: {known}", where=where)
        outcomes[stage] = _planned(value, where=f"{where}, стадия {key}")
    return outcomes


def _planned(raw: Any, *, where: str) -> tuple[Outcome, ...]:
    values = raw if isinstance(raw, list) else [raw]
    if not values:
        raise ModelError("перечень исходов пуст", where=where)

    planned: list[Outcome] = []
    for item in values:
        outcome = _OUTCOMES_BY_KEY.get(item) if isinstance(item, str) else None
        if outcome is None:
            known = ", ".join(_OUTCOMES_BY_KEY)
            raise ModelError(f"неизвестный исход {item!r}; известны: {known}", where=where)
        planned.append(outcome)
    return tuple(planned)
