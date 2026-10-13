"""Точка сборки ядра: адаптеры инфраструктуры — в сценарии.

Это единственное место, где создаются адаптеры (design D3 change `layer-forge-core`). Сборка —
обычный код без пакета внедрения зависимостей. Каждая фабрика аннотирована контрактом
сценария: контракты структурные и наследования не требуют, а mypy при каждой сборке проверяет,
что реализация контракт соблюдает.
"""

from __future__ import annotations

from pathlib import Path

from .contract.application.build_model import BuildModelUseCase, BuildModelUseCaseInterface
from .contract.application.diff_model import DiffModelUseCase, DiffModelUseCaseInterface
from .contract.infrastructure import YamlModelSource
from .delivery.application.show_norms import ShowNormsUseCase, ShowNormsUseCaseInterface
from .delivery.application.show_sample import ShowSampleUseCase, ShowSampleUseCaseInterface
from .delivery.infrastructure import PackageDeliveryFiles
from .intent.application.run_intent import RunIntentUseCase, RunIntentUseCaseInterface
from .intent.infrastructure import (
    FileRunHistory,
    FileRunReports,
    ScenarioSteps,
    YamlScenarioSource,
)
from .release.application.release_baseline import (
    ReleaseBaselineUseCase,
    ReleaseBaselineUseCaseInterface,
)
from .release.application.release_model import ReleaseModelUseCase, ReleaseModelUseCaseInterface
from .release.infrastructure.clock import SystemClock
from .release.infrastructure.files import (
    ChangelogPaths,
    FileMigrationNames,
    FileRegistryEntries,
    FileReleasedDescriptors,
    FileReleaseRepository,
)
from .release.infrastructure.postgres import PostgresDialect
from .store.application.list_checks import ListChecksUseCase, ListChecksUseCaseInterface
from .store.application.verify_store import VerifyStoreUseCase, VerifyStoreUseCaseInterface
from .store.infrastructure import (
    PostgresIntegrityProbe,
    PostgresIntegrityQueries,
    PostgresSchemaInspector,
    PostgresSession,
)


class Assembly:
    """Фабрика сценариев по каталогам вызова: реализация `Scenarios` входа ядра."""

    def build_model(self, model: Path) -> BuildModelUseCaseInterface:
        return BuildModelUseCase(YamlModelSource(model))

    def diff_model(self, model: Path, releases: Path, changelog: Path) -> DiffModelUseCaseInterface:
        paths = ChangelogPaths(model, releases, changelog)
        return DiffModelUseCase(YamlModelSource(model), FileReleasedDescriptors(paths))

    def release_model(
        self, model: Path, releases: Path, changelog: Path
    ) -> ReleaseModelUseCaseInterface:
        paths = ChangelogPaths(model, releases, changelog)
        return ReleaseModelUseCase(
            YamlModelSource(model),
            FileReleasedDescriptors(paths),
            PostgresDialect(),
            SystemClock(),
            FileMigrationNames(paths),
            FileReleaseRepository(paths),
        )

    def release_baseline(
        self, model: Path, releases: Path, changelog: Path
    ) -> ReleaseBaselineUseCaseInterface:
        paths = ChangelogPaths(model, releases, changelog)
        return ReleaseBaselineUseCase(
            YamlModelSource(model),
            PostgresDialect(),
            SystemClock(),
            FileMigrationNames(paths),
            FileReleaseRepository(paths),
        )

    def list_checks(self, model: Path) -> ListChecksUseCaseInterface:
        return ListChecksUseCase(YamlModelSource(model), PostgresIntegrityQueries())

    def verify_store(self, model: Path, changelog: Path, dsn: str) -> VerifyStoreUseCaseInterface:
        session = PostgresSession(dsn)
        # Реестр читается из каталога миграций; каталог выпущенных дескрипторов сверке не нужен,
        # и ключа для него у подкоманды нет.
        registry = FileRegistryEntries(ChangelogPaths(model, model, changelog))
        return VerifyStoreUseCase(
            YamlModelSource(model),
            registry,
            PostgresSchemaInspector(session.fetch),
            PostgresIntegrityQueries(),
            PostgresIntegrityProbe(session.fetch),
        )

    def run_intent(self, runs: Path) -> RunIntentUseCaseInterface:
        return RunIntentUseCase(
            YamlScenarioSource(), ScenarioSteps(), FileRunHistory(runs), FileRunReports(runs)
        )

    def show_norms(self) -> ShowNormsUseCaseInterface:
        return ShowNormsUseCase(PackageDeliveryFiles())

    def show_sample(self) -> ShowSampleUseCaseInterface:
        return ShowSampleUseCase(PackageDeliveryFiles())
