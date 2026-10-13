"""Сценарий `forge norms`: все нормы модели с глоссарием либо раздел одной нормы.

Сценарий тонкий: состав выдачи — нормы, за ними глоссарий — решается здесь, а чтение файлов
и вырезание раздела по заголовку остаются за контрактом файлов поставки.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import SHOWN, DeliveryFiles


@dataclass(frozen=True, slots=True)
class ShowNormsInput:
    """Код правила, например `MDL-009`; `None` — все нормы и глоссарий."""

    rule: str | None = None


@dataclass(frozen=True, slots=True)
class ShowNormsOutput:
    """Исход и текст выдачи."""

    outcome: str
    text: str


class ShowNormsUseCaseInterface(Protocol):
    """Контракт сценария выдачи норм: от него зависит вход ядра."""

    def execute(self, request: ShowNormsInput) -> ShowNormsOutput: ...


class ShowNormsUseCase:
    """Реализация `ShowNormsUseCaseInterface`."""

    def __init__(self, files: DeliveryFiles) -> None:
        self._files = files

    def execute(self, request: ShowNormsInput) -> ShowNormsOutput:
        if request.rule is not None:
            return ShowNormsOutput(SHOWN, self._files.rule(request.rule))
        text = f"{self._files.rules().rstrip()}\n\n{self._files.glossary().rstrip()}\n"
        return ShowNormsOutput(SHOWN, text)
