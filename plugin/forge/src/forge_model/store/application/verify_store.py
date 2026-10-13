"""Сценарий `forge verify`: сверить хранилище с моделью и прогнать проверки целостности.

Сценарий-запрос: конструктор принимает только контракты чтения (APB-005 (3)). Порядок сверки
прежний: неизменяемость выпущенных файлов, колонки таблиц ревизий, отпечаток версии, правила
целостности. Расхождения — штатный исход со списком, недоступное хранилище — ошибка окружения.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...contract.domain import compile_descriptor
from ..domain import (
    expected_columns,
    integrity_rules,
    released_file_finding,
    schema_drifts,
    stamp_drifts,
    violation,
)
from .contracts import (
    DRIFTED,
    REJECTED,
    VERIFIED,
    Discrepancy,
    IntegrityProbe,
    IntegrityQueries,
    ModelSource,
    RegistryEntries,
    SchemaInspector,
    discrepancies,
)


@dataclass(frozen=True, slots=True)
class VerifyStoreInput:
    """Сценарий параметров не принимает: хранилище и каталоги — у источников."""


@dataclass(frozen=True, slots=True)
class VerifyStoreOutput:
    """Исход, сводка для печати и расхождения: модели либо хранилища с моделью."""

    outcome: str
    summary: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class VerifyStoreUseCaseInterface(Protocol):
    """Контракт сценария сверки хранилища: от него зависит вход ядра."""

    def execute(self, request: VerifyStoreInput) -> VerifyStoreOutput: ...


class VerifyStoreUseCase:
    """Реализация `VerifyStoreUseCaseInterface`."""

    def __init__(
        self,
        source: ModelSource,
        registry: RegistryEntries,
        inspector: SchemaInspector,
        queries: IntegrityQueries,
        probe: IntegrityProbe,
    ) -> None:
        self._source = source
        self._registry = registry
        self._inspector = inspector
        self._queries = queries
        self._probe = probe

    def execute(self, request: VerifyStoreInput) -> VerifyStoreOutput:
        compilation = compile_descriptor(self._source.read())
        descriptor = compilation.descriptor
        if descriptor is None:
            return VerifyStoreOutput(REJECTED, discrepancies=discrepancies(compilation.findings))

        found = [
            Discrepancy(f"changelog: {finding.place}", f"{finding.element} {finding.message}")
            for item in self._registry.files()
            if (
                finding := released_file_finding(
                    item.address, item.version, item.recorded, item.actual
                )
            )
        ]
        drifts = (
            *schema_drifts(expected_columns(descriptor), self._inspector.columns()),
            *stamp_drifts(descriptor, self._inspector.stamp()),
        )
        found += [Discrepancy(f"схема: {drift.where}", drift.detail) for drift in drifts]
        for rule in integrity_rules(descriptor):
            broken = violation(rule, self._probe.offenders(self._queries.sql(rule)))
            if broken is not None:
                found.append(Discrepancy(f"целостность: {broken.check}", broken.description))

        if found:
            return VerifyStoreOutput(DRIFTED, discrepancies=tuple(found))
        return VerifyStoreOutput(
            VERIFIED, summary=(f"схема соответствует модели {descriptor.version}",)
        )
