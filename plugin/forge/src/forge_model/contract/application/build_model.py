"""Сценарий `forge build`: собрать дескриптор рабочей модели и назвать его хеш.

Сценарий-запрос: он ничего не пишет. Модель с нарушениями — штатный исход «отвергнуто»
с перечнем всех нарушений, а не исключение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import compile_descriptor
from .contracts import BUILT, REJECTED, Discrepancy, ModelSource, discrepancies


@dataclass(frozen=True, slots=True)
class BuildModelInput:
    """Сценарий параметров не принимает: модель читает источник."""


@dataclass(frozen=True, slots=True)
class BuildModelOutput:
    """Исход, сводка для печати и расхождения отвергнутой модели."""

    outcome: str
    summary: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class BuildModelUseCaseInterface(Protocol):
    """Контракт сценария сборки модели: от него зависит вход ядра."""

    def execute(self, request: BuildModelInput) -> BuildModelOutput: ...


class BuildModelUseCase:
    """Реализация `BuildModelUseCaseInterface`."""

    def __init__(self, source: ModelSource) -> None:
        self._source = source

    def execute(self, request: BuildModelInput) -> BuildModelOutput:
        compilation = compile_descriptor(self._source.read())
        descriptor = compilation.descriptor
        if descriptor is None:
            return BuildModelOutput(REJECTED, discrepancies=discrepancies(compilation.findings))
        return BuildModelOutput(
            BUILT, summary=(f"{descriptor.model} {descriptor.version}  {descriptor.hash}",)
        )
