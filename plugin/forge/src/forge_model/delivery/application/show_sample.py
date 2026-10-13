"""Сценарий `forge sample`: образец минимальной модели одним текстом.

Файлы образца выдаются подряд, каждому предшествует разделитель с путём от корня проекта:
по разделителям вывод раскладывается обратно в файлы. Формат разделителя — часть выдачи,
поэтому он задан здесь, а не в инфраструктуре.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from .contracts import SHOWN, DeliveryFiles

#: Разделитель файлов в выводе образца: путь файла относительно корня проекта.
SEPARATOR: Final = "==> {path} <=="


@dataclass(frozen=True, slots=True)
class ShowSampleInput:
    """Сценарий параметров не принимает: образец в поставке один."""


@dataclass(frozen=True, slots=True)
class ShowSampleOutput:
    """Исход и текст образца."""

    outcome: str
    text: str


class ShowSampleUseCaseInterface(Protocol):
    """Контракт сценария выдачи образца: от него зависит вход ядра."""

    def execute(self, request: ShowSampleInput) -> ShowSampleOutput: ...


class ShowSampleUseCase:
    """Реализация `ShowSampleUseCaseInterface`."""

    def __init__(self, files: DeliveryFiles) -> None:
        self._files = files

    def execute(self, request: ShowSampleInput) -> ShowSampleOutput:
        chunks = [
            f"{SEPARATOR.format(path=path)}\n{text.rstrip()}\n"
            for path, text in self._files.sample()
        ]
        return ShowSampleOutput(SHOWN, "\n".join(chunks))
