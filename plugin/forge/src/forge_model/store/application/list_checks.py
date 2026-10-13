"""Сценарий `forge checks`: напечатать запросы проверок целостности рабочей модели.

Сценарий-запрос: к хранилищу он не обращается — печатает имя правила, его предмет и текст
запроса, чтобы проверку можно было выполнить вне входа.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...contract.domain import compile_descriptor
from ..domain import integrity_rules
from .contracts import LISTED, REJECTED, Discrepancy, IntegrityQueries, ModelSource, discrepancies


@dataclass(frozen=True, slots=True)
class ListChecksInput:
    """Сценарий параметров не принимает: правила выводятся из модели."""


@dataclass(frozen=True, slots=True)
class ListChecksOutput:
    """Исход, запросы проверок для печати и расхождения отвергнутой модели."""

    outcome: str
    summary: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class ListChecksUseCaseInterface(Protocol):
    """Контракт сценария перечня проверок: от него зависит вход ядра."""

    def execute(self, request: ListChecksInput) -> ListChecksOutput: ...


class ListChecksUseCase:
    """Реализация `ListChecksUseCaseInterface`."""

    def __init__(self, source: ModelSource, queries: IntegrityQueries) -> None:
        self._source = source
        self._queries = queries

    def execute(self, request: ListChecksInput) -> ListChecksOutput:
        compilation = compile_descriptor(self._source.read())
        if compilation.descriptor is None:
            return ListChecksOutput(REJECTED, discrepancies=discrepancies(compilation.findings))
        return ListChecksOutput(
            LISTED,
            summary=tuple(
                f"-- {rule.name}: {rule.subject}\n{self._queries.sql(rule)}\n"
                for rule in integrity_rules(compilation.descriptor)
            ),
        )
