"""Сценарий `forge gen`: выпустить версию модели — миграции, дескриптор, реестр.

Порядок шагов повторяет прежний выпуск: собрать дескриптор, решить по гейту совместимости,
при «выпускать нечего» вернуть исход без записи, построить шаги и тексты миграций, пополнить
занятые номера и пересобрать дескриптор в домене, собрать агрегат выпуска и передать его
контракту записи одним вызовом (design D6). Правила — в доменах; сценарий решает только,
в каком порядке их вызвать.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ...contract import domain as contract
from ...contract.domain import CompatibilityGate, compile_descriptor
from ..domain import (
    CORE,
    RELEASE_EXISTS,
    Migration,
    Release,
    ReleaseRepository,
    closing_comment,
    migration_names,
    migration_steps,
    migration_text,
    replenished,
    taken_fields,
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
    ReleasedDescriptors,
    discrepancies,
)


@dataclass(frozen=True, slots=True)
class ReleaseModelInput:
    """Сценарий параметров не принимает: модель, выпуски и каталог миграций — у источников."""


@dataclass(frozen=True, slots=True)
class ReleaseModelOutput:
    """Исход, сводка для печати, адреса выпущенных миграций и расхождения отказа.

    Адрес миграции — путь от корня каталога миграций.
    """

    outcome: str
    summary: tuple[str, ...] = ()
    released: tuple[str, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()


class ReleaseModelUseCaseInterface(Protocol):
    """Контракт сценария выпуска версии: от него зависит вход ядра."""

    def execute(self, request: ReleaseModelInput) -> ReleaseModelOutput: ...


class ReleaseModelUseCase:
    """Реализация `ReleaseModelUseCaseInterface`."""

    def __init__(
        self,
        source: ModelSource,
        released: ReleasedDescriptors,
        dialect: MigrationDialect,
        clock: Clock,
        names: MigrationNames,
        repository: ReleaseRepository,
    ) -> None:
        self._source = source
        self._released = released
        self._dialect = dialect
        self._clock = clock
        self._names = names
        self._repository = repository

    def execute(self, request: ReleaseModelInput) -> ReleaseModelOutput:
        compilation = compile_descriptor(self._source.read())
        current = compilation.descriptor
        if current is None:
            return ReleaseModelOutput(REJECTED, discrepancies=discrepancies(compilation.findings))

        decision = CompatibilityGate().decide(current, self._released.latest(current.major))
        if decision.outcome == contract.REJECTED:
            return ReleaseModelOutput(REJECTED, discrepancies=discrepancies(decision.findings))
        report = decision.report()
        if decision.outcome == contract.NOTHING_TO_RELEASE:
            return ReleaseModelOutput(NOTHING_TO_RELEASE, summary=report)

        version = str(current.version)
        steps = migration_steps(decision.delta)
        texts = [
            migration_text(step.slug, version, step.comment, *self._dialect.render(step))
            for step in steps
        ]
        previous_hash = decision.previous.hash if decision.previous else None
        statements, rollback, precondition = self._dialect.close_version(
            previous_hash, version, current.hash
        )
        texts.append(
            migration_text(
                f"close.{version}",
                version,
                closing_comment(decision.previous, version, decision.delta),
                statements,
                rollback,
                precondition=precondition,
            )
        )
        taken = taken_fields(decision.delta)
        release = Release(
            current.version,
            replenished(current, taken),
            self._migrations([step.folder for step in steps] + [CORE], texts),
            taken,
        )

        if self._repository.add(release) == RELEASE_EXISTS:
            return ReleaseModelOutput(
                NOTHING_TO_RELEASE,
                summary=(*report, f"адрес выпуска {version} занят: выпущенное не перезаписывается"),
            )
        recorded = tuple(
            f"занято навсегда: {code}.{field.id} ({field.name})" for code, field in taken
        )
        return ReleaseModelOutput(RELEASED, summary=(*report, *recorded), released=release.order)

    def _migrations(self, folders: Sequence[str], texts: Sequence[str]) -> tuple[Migration, ...]:
        taken = {folder: self._names.taken(folder) for folder in set(folders)}
        names = migration_names(folders, self._clock.now(), taken)
        return tuple(
            Migration(folder, name, text)
            for folder, name, text in zip(folders, names, texts, strict=True)
        )
