"""Вход ядра: ключи и каталоги вызова, сценарии подкоманд, перевод исхода в текст и код возврата.

Вход зависит только от контрактов сценариев, `EnvironmentFault` и фабрики сценариев; правил
модели, выпуска и сверки в нём нет (design D3 change `layer-forge-core`). Обработчик подкоманды
строит входной контракт из ключей, получает сценарий у фабрики по каталогам, печатает выходной
контракт и возвращает код по исходу. Фабрика по умолчанию — точка сборки `assembly.py`; тест
подставляет свою и проверяет, что вход исполняет любую реализацию контракта сценария.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .assembly import Assembly
from .contract.application import contracts as model_outcomes
from .contract.application.build_model import BuildModelInput, BuildModelUseCaseInterface
from .contract.application.diff_model import DiffModelInput, DiffModelUseCaseInterface
from .delivery.application import contracts as delivery_outcomes
from .delivery.application.show_norms import ShowNormsInput, ShowNormsUseCaseInterface
from .delivery.application.show_sample import ShowSampleInput, ShowSampleUseCaseInterface
from .errors import EnvironmentFault
from .intent.application import contracts as intent_outcomes
from .intent.application.run_intent import (
    DEFAULT_MAX_ITERATIONS,
    RunIntentInput,
    RunIntentUseCaseInterface,
)
from .release.application import contracts as release_outcomes
from .release.application.release_baseline import (
    ReleaseBaselineInput,
    ReleaseBaselineUseCaseInterface,
)
from .release.application.release_model import ReleaseModelInput, ReleaseModelUseCaseInterface
from .store.application import contracts as store_outcomes
from .store.application.list_checks import ListChecksInput, ListChecksUseCaseInterface
from .store.application.verify_store import VerifyStoreInput, VerifyStoreUseCaseInterface


class Scenarios(Protocol):
    """Фабрика сценариев подкоманд по каталогам вызова."""

    def build_model(self, model: Path) -> BuildModelUseCaseInterface: ...

    def diff_model(
        self, model: Path, releases: Path, changelog: Path
    ) -> DiffModelUseCaseInterface: ...

    def release_model(
        self, model: Path, releases: Path, changelog: Path
    ) -> ReleaseModelUseCaseInterface: ...

    def release_baseline(
        self, model: Path, releases: Path, changelog: Path
    ) -> ReleaseBaselineUseCaseInterface: ...

    def list_checks(self, model: Path) -> ListChecksUseCaseInterface: ...

    def verify_store(
        self, model: Path, changelog: Path, dsn: str
    ) -> VerifyStoreUseCaseInterface: ...

    def run_intent(self, runs: Path) -> RunIntentUseCaseInterface: ...

    def show_norms(self) -> ShowNormsUseCaseInterface: ...

    def show_sample(self) -> ShowSampleUseCaseInterface: ...


#: Обработчик подкоманды: ключи вызова и фабрика сценариев — код возврата.
Handler = Callable[[argparse.Namespace, Scenarios], int]


# Умолчания каталогов — пути относительно корня проекта, а не рабочего каталога: вход
# вызывается из любого подкаталога проекта-потребителя и читает одну и ту же модель.
DEFAULT_MODEL = Path("model/forge.reqs.v1")
DEFAULT_RELEASES = Path("model/releases")
DEFAULT_CHANGELOG = Path("changelog")
DEFAULT_RUNS = Path("model/intents/runs")

#: Каталог: ключ вызова, переменная окружения, умолчание от корня проекта. Приоритет — в этом
#: порядке. Относительный путь ключа считается от рабочего каталога, как принято у командной
#: строки; относительный путь переменной и умолчание — от корня проекта.
DIRECTORIES = {
    "model": ("FORGE_MODEL_DIR", DEFAULT_MODEL),
    "releases": ("FORGE_RELEASES_DIR", DEFAULT_RELEASES),
    "changelog": ("FORGE_CHANGELOG_DIR", DEFAULT_CHANGELOG),
    "runs": ("FORGE_RUNS_DIR", DEFAULT_RUNS),
}

# Единая таблица кодов возврата всех подкоманд.
EXIT_OK = 0
#: Ввод отвергнут или найдены расхождения, включая незамкнутый цикл намерения.
EXIT_REJECTED = 1
#: Ошибка вызова или окружения, включая ошибку процесса цикла. Тот же код даёт argparse.
EXIT_ENVIRONMENT = 2


def main(argv: list[str] | None = None, *, scenarios: Scenarios | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    # Обработчик подставлен разбором аргументов и из Namespace приходит нетипизированным:
    # тип объявляется здесь, у единственной точки вызова.
    handler: Handler = args.handler
    try:
        _resolve_directories(args)
        return handler(args, scenarios if scenarios is not None else Assembly())
    except EnvironmentFault as error:
        print(f"ОШИБКА  {error}", file=sys.stderr)
        return EXIT_ENVIRONMENT


def _project_root() -> Path:
    """Корень проекта-потребителя: `CLAUDE_PROJECT_DIR`, иначе ближайший вверх каталог с `.git`."""
    declared = os.environ.get("CLAUDE_PROJECT_DIR")
    if declared:
        return Path(declared)
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise EnvironmentFault(
        "корень проекта не найден: задайте CLAUDE_PROJECT_DIR или вызовите вход внутри "
        "репозитория git",
        where=str(here),
    )


def _resolve_directories(args: argparse.Namespace) -> None:
    """Подставить каталоги, не переданные ключом: из переменной окружения или умолчания.

    Корень проекта ищется, только если он нужен: вызов со всеми каталогами в ключах работает
    и вне проекта.
    """
    for name, (variable, default) in DIRECTORIES.items():
        if getattr(args, name, ...) is not None:
            continue
        value = os.environ.get(variable)
        path = Path(value) if value else default
        setattr(args, name, path if path.is_absolute() else _project_root() / path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge", description="Контракт модели данных графа требований"
    )
    sub = parser.add_subparsers(required=True)

    for name, handler, help_text in (
        ("build", _build, "собрать дескриптор рабочей модели"),
        ("diff", _diff, "сравнить рабочую модель с последней выпущенной версией"),
        ("gen", _gen, "выпустить версию: миграции, дескриптор, реестр"),
        ("checks", _checks, "напечатать запросы проверок целостности"),
    ):
        command = sub.add_parser(name, help=help_text)
        _directory(command, "model")
        _directory(command, "releases")
        _directory(command, "changelog")
        command.add_argument(
            "--baseline", action="store_true", help="выпустить свёртку модели целиком"
        )
        command.set_defaults(handler=handler)

    verify = sub.add_parser("verify", help="сверить схему хранилища с моделью и прогнать проверки")
    _directory(verify, "model")
    _directory(verify, "changelog")
    verify.add_argument("--dsn", required=True, help="строка подключения к хранилищу")
    verify.set_defaults(handler=_verify)

    norms = sub.add_parser("norms", help="напечатать нормы модели и глоссарий")
    norms.add_argument("--rule", metavar="КОД", help="напечатать одно правило, например MDL-001")
    norms.set_defaults(handler=_norms)

    sample = sub.add_parser("sample", help="напечатать образец минимальной модели")
    sample.set_defaults(handler=_sample)

    _intent_parser(sub)
    return parser


def _directory(command: argparse.ArgumentParser, name: str) -> None:
    variable, default = DIRECTORIES[name]
    command.add_argument(
        f"--{name}",
        type=Path,
        default=None,
        help=f"по умолчанию ${variable}, иначе {default.as_posix()} от корня проекта",
    )


def _intent_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    intent = sub.add_parser("intent", help="цикл намерения")
    actions = intent.add_subparsers(required=True)

    run = actions.add_parser("run", help="прогнать цикл намерения по сценарию")
    run.add_argument("--scenario", type=Path, required=True, help="файл сценария прогона")
    _directory(run, "runs")
    run.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f"лимит итераций (по умолчанию {DEFAULT_MAX_ITERATIONS})",
    )
    run.set_defaults(handler=_intent_run)


def _build(args: argparse.Namespace, scenarios: Scenarios) -> int:
    return _reported(scenarios.build_model(args.model).execute(BuildModelInput()))


def _diff(args: argparse.Namespace, scenarios: Scenarios) -> int:
    scenario = scenarios.diff_model(args.model, args.releases, args.changelog)
    return _reported(scenario.execute(DiffModelInput()))


class _Place(Protocol):
    """Расхождение выходного контракта: место и сообщение."""

    @property
    def place(self) -> str: ...

    @property
    def message(self) -> str: ...


class _Report(Protocol):
    """Выходной контракт сценария с исходом, сводкой и расхождениями."""

    @property
    def outcome(self) -> str: ...

    @property
    def summary(self) -> tuple[str, ...]: ...

    @property
    def discrepancies(self) -> tuple[_Place, ...]: ...


class _Release(_Report, Protocol):
    """Выходной контракт выпуска: ещё и адреса выпущенных миграций."""

    @property
    def released(self) -> tuple[str, ...]: ...


#: Код возврата по исходу сценария.
EXIT_BY_OUTCOME = {
    model_outcomes.BUILT: EXIT_OK,
    model_outcomes.COMPARED: EXIT_OK,
    model_outcomes.NOTHING_TO_RELEASE: EXIT_OK,
    model_outcomes.REJECTED: EXIT_REJECTED,
    release_outcomes.RELEASED: EXIT_OK,
    release_outcomes.NOTHING_TO_RELEASE: EXIT_OK,
    release_outcomes.REJECTED: EXIT_REJECTED,
    store_outcomes.LISTED: EXIT_OK,
    store_outcomes.VERIFIED: EXIT_OK,
    store_outcomes.DRIFTED: EXIT_REJECTED,
    store_outcomes.REJECTED: EXIT_REJECTED,
    intent_outcomes.CLOSED: EXIT_OK,
    intent_outcomes.NOT_CLOSED: EXIT_REJECTED,
    intent_outcomes.REJECTED: EXIT_REJECTED,
    intent_outcomes.PROCESS_ERROR: EXIT_ENVIRONMENT,
    delivery_outcomes.SHOWN: EXIT_OK,
}

#: Пометка расхождения в диагностике: отказ ввода — ошибка, расхождение с хранилищем — факт.
LABEL_BY_OUTCOME = {store_outcomes.DRIFTED: "РАСХОЖДЕНИЕ"}


def _reported(output: _Report, after: tuple[str, ...] = ()) -> int:
    """Напечатать выходной контракт: сводку — в вывод, расхождения — в диагностику."""
    for line in (*output.summary, *after):
        print(line)
    label = LABEL_BY_OUTCOME.get(output.outcome, "ОШИБКА")
    for discrepancy in output.discrepancies:
        print(f"{label}  {discrepancy.place}: {discrepancy.message}", file=sys.stderr)
    return EXIT_BY_OUTCOME[output.outcome]


def _gen(args: argparse.Namespace, scenarios: Scenarios) -> int:
    output: _Release
    if args.baseline:
        baseline = scenarios.release_baseline(args.model, args.releases, args.changelog)
        output = baseline.execute(ReleaseBaselineInput())
    else:
        release = scenarios.release_model(args.model, args.releases, args.changelog)
        output = release.execute(ReleaseModelInput())
    released = tuple(f"выпущено: {args.changelog / address}" for address in output.released)
    return _reported(output, released)


def _checks(args: argparse.Namespace, scenarios: Scenarios) -> int:
    return _reported(scenarios.list_checks(args.model).execute(ListChecksInput()))


def _verify(args: argparse.Namespace, scenarios: Scenarios) -> int:
    scenario = scenarios.verify_store(args.model, args.changelog, args.dsn)
    return _reported(scenario.execute(VerifyStoreInput()))


def _intent_run(args: argparse.Namespace, scenarios: Scenarios) -> int:
    created = not args.runs.exists()
    try:
        output = scenarios.run_intent(args.runs).execute(
            RunIntentInput(scenario=args.scenario, max_iterations=args.max_iterations)
        )
    finally:
        if created and args.runs.exists():
            _recommend_ignore(args.runs)
    return _reported(output)


def _recommend_ignore(runs: Path) -> None:
    """Напомнить, что отчёты прогонов — не артефакт репозитория. `.gitignore` не правится."""
    try:
        root = _project_root().resolve()
        relative = runs.resolve().relative_to(root).as_posix()
    except (EnvironmentFault, ValueError):
        return
    ignore = root / ".gitignore"
    listed = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if relative in {line.strip().strip("/") for line in listed}:
        return
    print(
        f"РЕКОМЕНДАЦИЯ  добавьте в .gitignore строку {relative}/ — "
        "отчёты прогонов цикла не коммитятся",
        file=sys.stderr,
    )


def _norms(args: argparse.Namespace, scenarios: Scenarios) -> int:
    output = scenarios.show_norms().execute(ShowNormsInput(rule=args.rule))
    print(output.text, end="")
    return EXIT_BY_OUTCOME[output.outcome]


def _sample(args: argparse.Namespace, scenarios: Scenarios) -> int:
    output = scenarios.show_sample().execute(ShowSampleInput())
    print(output.text, end="")
    return EXIT_BY_OUTCOME[output.outcome]
