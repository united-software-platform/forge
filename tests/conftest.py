"""Общие приспособления тестов."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from forge_model.contract.domain import Descriptor, compile_descriptor
from forge_model.contract.infrastructure import YamlModelSource
from forge_model.intent.application.contracts import ScenarioReading, Steps
from forge_model.intent.application.run_intent import (
    DEFAULT_MAX_ITERATIONS,
    RunIntentInput,
    RunIntentOutput,
    RunIntentUseCase,
)
from forge_model.intent.domain import RunScenario
from forge_model.intent.infrastructure import FileRunHistory, FileRunReports, ScenarioSteps
from forge_model.release.application.release_baseline import (
    ReleaseBaselineInput,
    ReleaseBaselineOutput,
    ReleaseBaselineUseCase,
)
from forge_model.release.application.release_model import (
    ReleaseModelInput,
    ReleaseModelOutput,
    ReleaseModelUseCase,
)
from forge_model.release.infrastructure.files import (
    ChangelogPaths,
    FileMigrationNames,
    FileReleaseRepository,
)
from forge_model.release.infrastructure.postgres import PostgresDialect
from forge_model.store.domain import (
    IntegrityViolation,
    SchemaDrift,
    expected_columns,
    integrity_rules,
    schema_drifts,
    stamp_drifts,
    violation,
)
from forge_model.store.infrastructure import (
    Fetch,
    PostgresIntegrityProbe,
    PostgresIntegrityQueries,
    PostgresSchemaInspector,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def model_root() -> Path:
    """Каталог образцовой модели `forge.reqs.v1`."""
    return FIXTURES / "model" / "forge.reqs.v1"


@pytest.fixture
def model_copy(model_root: Path, tmp_path: Path) -> Path:
    """Копия образцовой модели, которую тест может править."""
    import shutil

    target = tmp_path / "forge.reqs.v1"
    shutil.copytree(model_root, target)
    return target


@pytest.fixture
def trade_model() -> Path:
    """Каталог демонстрационной модели предметной области «торговля»."""
    return FIXTURES / "model" / "trade.v1"


@pytest.fixture
def trade_copy(trade_model: Path, tmp_path: Path) -> Path:
    """Копия демонстрационной модели, которую тест проводит через выпуски версий."""
    import shutil

    target = tmp_path / "trade.v1"
    shutil.copytree(trade_model, target)
    return target


def statements_of(path: Path) -> list[str]:
    """Операторы SQL из файла миграции: служебные строки Liquibase отбрасываются."""
    body = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("--")
    ]
    return [chunk + ";" for chunk in "\n".join(body).split(";") if chunk.strip()]


def compiled(root: Path) -> Descriptor:
    """Дескриптор модели каталога; модель с нарушениями роняет тест перечнем нарушений."""
    compilation = compile_descriptor(YamlModelSource(root).read())
    assert compilation.descriptor is not None, compilation.findings
    return compilation.descriptor


#: Часы выпусков в тестах: метка времени входит в имена файлов миграций.
MOMENT = datetime(2026, 9, 15, 14, 22, 33, tzinfo=UTC)


class FixedClock:
    """Часы, показывающие одно и то же время."""

    def __init__(self, moment: datetime = MOMENT) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class Released:
    """Выпущенная версия, заданная тестом, вместо каталога выпущенных дескрипторов."""

    def __init__(self, descriptor: Descriptor | None) -> None:
        self._descriptor = descriptor

    def latest(self, major: int) -> Descriptor | None:
        return self._descriptor


def changelog_paths(model: Path, changelog: Path) -> ChangelogPaths:
    """Адреса выпуска: выпущенные дескрипторы — рядом с каталогом миграций."""
    return ChangelogPaths(model, changelog.parent / "releases", changelog)


def release(
    model: Path, changelog: Path, previous: Descriptor | None, moment: datetime = MOMENT
) -> ReleaseModelOutput:
    """Выпустить версию модели каталога поверх заданной выпущенной версии."""
    paths = changelog_paths(model, changelog)
    return ReleaseModelUseCase(
        YamlModelSource(model),
        Released(previous),
        PostgresDialect(),
        FixedClock(moment),
        FileMigrationNames(paths),
        FileReleaseRepository(paths),
    ).execute(ReleaseModelInput())


def baseline(model: Path, changelog: Path, moment: datetime = MOMENT) -> ReleaseBaselineOutput:
    """Выпустить свёртку модели каталога."""
    paths = changelog_paths(model, changelog)
    return ReleaseBaselineUseCase(
        YamlModelSource(model),
        PostgresDialect(),
        FixedClock(moment),
        FileMigrationNames(paths),
        FileReleaseRepository(paths),
    ).execute(ReleaseBaselineInput())


def store_violations(descriptor: Descriptor, fetch: Fetch) -> list[IntegrityViolation]:
    """Нарушения правил целостности дескриптора в хранилище за `fetch`."""
    queries, probe = PostgresIntegrityQueries(), PostgresIntegrityProbe(fetch)
    return [
        broken
        for rule in integrity_rules(descriptor)
        if (broken := violation(rule, probe.offenders(queries.sql(rule)))) is not None
    ]


def store_drifts(descriptor: Descriptor, fetch: Fetch) -> list[SchemaDrift]:
    """Расхождения схемы хранилища за `fetch` с дескриптором: колонки и отпечаток версии."""
    inspector = PostgresSchemaInspector(fetch)
    return [
        *schema_drifts(expected_columns(descriptor), inspector.columns()),
        *stamp_drifts(descriptor, inspector.stamp()),
    ]


class GivenScenario:
    """Сценарий прогона, заданный тестом, вместо файла сценария."""

    def __init__(self, scenario: RunScenario) -> None:
        self._scenario = scenario

    def read(self, path: Path) -> ScenarioReading:
        return ScenarioReading(self._scenario)


class GivenSteps:
    """Набор шагов, заданный тестом, вместо подставных шагов по сценарию."""

    def __init__(self, steps: Steps) -> None:
        self._steps = steps

    def steps(self, scenario: RunScenario) -> Steps:
        return self._steps


def run_intent(
    runs: Path,
    scenario: RunScenario,
    steps: Steps | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> RunIntentOutput:
    """Прогнать цикл намерения по сценарию; отчёты — в каталоге `runs`."""
    factory = ScenarioSteps() if steps is None else GivenSteps(steps)
    return RunIntentUseCase(
        GivenScenario(scenario), factory, FileRunHistory(runs), FileRunReports(runs)
    ).execute(RunIntentInput(runs / "scenario.yaml", max_iterations))
