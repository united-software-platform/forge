"""Сценарий `forge gen --baseline`: выпустить свёртку модели целиком.

Свёртка — начальная миграция пустого хранилища и замыкающая миграция с отпечатком версии
(MDL-037). Гейт совместимости свёртку не проверяет: она не продолжает историю выпусков,
а выводит схему из дескриптора заново.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...contract.domain import compile_descriptor
from ..domain import (
    BASELINE_ROLLBACK,
    CORE,
    RELEASE_EXISTS,
    Migration,
    Release,
    ReleaseRepository,
    baseline_comment,
    migration_names,
    migration_text,
    stamp_comment,
)
from .contracts import (
    NOTHING_TO_RELEASE,
    REJECTED,
    RELEASED,
    Clock,
    Discrepancy,
    MigrationDialect,
    MigrationNames,
    ModelSource,
    discrepancies,
)


@dataclass(frozen=True, slots=True)
class ReleaseBaselineInput:
    """Сценарий параметров не принимает: модель и каталог миграций — у источников."""


@dataclass(frozen=True, slots=True)
class ReleaseBaselineOutput:
    """Исход, сводка для печати, адреса выпущенных миграций и расхождения отказа."""

    outcome: str
    summary: tuple[str, ...] = ()
    released: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class ReleaseBaselineUseCaseInterface(Protocol):
    """Контракт сценария выпуска свёртки: от него зависит вход ядра."""

    def execute(self, request: ReleaseBaselineInput) -> ReleaseBaselineOutput: ...


class ReleaseBaselineUseCase:
    """Реализация `ReleaseBaselineUseCaseInterface`."""

    def __init__(
        self,
        source: ModelSource,
        dialect: MigrationDialect,
        clock: Clock,
        names: MigrationNames,
        repository: ReleaseRepository,
    ) -> None:
        self._source = source
        self._dialect = dialect
        self._clock = clock
        self._names = names
        self._repository = repository

    def execute(self, request: ReleaseBaselineInput) -> ReleaseBaselineOutput:
        compilation = compile_descriptor(self._source.read())
        descriptor = compilation.descriptor
        if descriptor is None:
            return ReleaseBaselineOutput(
                REJECTED, discrepancies=discrepancies(compilation.findings)
            )

        version = str(descriptor.version)
        statements, rollback, _ = self._dialect.close_version(None, version, descriptor.hash)
        texts = (
            migration_text(
                f"baseline.{version}",
                version,
                baseline_comment(descriptor),
                self._dialect.baseline_statements(descriptor),
                BASELINE_ROLLBACK,
            ),
            migration_text(
                f"close.{version}", version, stamp_comment(version), statements, rollback
            ),
        )
        folders = (CORE, CORE)
        names = migration_names(folders, self._clock.now(), {CORE: self._names.taken(CORE)})
        release = Release(
            descriptor.version,
            descriptor,
            tuple(
                Migration(folder, name, text)
                for folder, name, text in zip(folders, names, texts, strict=True)
            ),
        )

        if self._repository.add(release) == RELEASE_EXISTS:
            return ReleaseBaselineOutput(
                NOTHING_TO_RELEASE,
                summary=(f"адрес выпуска {version} занят: выпущенное не перезаписывается",),
            )
        return ReleaseBaselineOutput(RELEASED, released=release.order)
