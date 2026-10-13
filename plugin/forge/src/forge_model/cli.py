"""Командная строка: сборка модели, сравнение, выпуск, проверки."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import delivery, registry
from .checks import checks_for, run_checks
from .descriptor import compile_model, dump_descriptor
from .errors import EnvironmentFault, ModelError
from .gen.changelog import emit, emit_baseline
from .intent.engine import DEFAULT_MAX_ITERATIONS, run_cycle
from .intent.mock import steps_for
from .intent.scenario import load_scenario
from .model import load_model
from .release import find_previous, plan_release, record_taken
from .verify import verify_schema

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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    # Обработчик подставлен разбором аргументов и из Namespace приходит нетипизированным:
    # тип объявляется здесь, у единственной точки вызова.
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        _resolve_directories(args)
        return handler(args)
    except EnvironmentFault as error:
        print(f"ОШИБКА  {error}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    except ModelError as error:
        print(f"ОШИБКА  {error}", file=sys.stderr)
        return EXIT_REJECTED


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


def _descriptor(args: argparse.Namespace) -> dict[str, Any]:
    return compile_model(load_model(args.model))


def _build(args: argparse.Namespace) -> int:
    descriptor = _descriptor(args)
    print(f"{descriptor['model']} {descriptor['version']}  {descriptor['hash']}")
    return EXIT_OK


def _diff(args: argparse.Namespace) -> int:
    descriptor = _descriptor(args)
    previous = find_previous(args.releases, descriptor["major"])
    print(plan_release(descriptor, previous).report())
    return EXIT_OK


def _gen(args: argparse.Namespace) -> int:
    descriptor = _descriptor(args)
    previous = find_previous(args.releases, descriptor["major"])

    if args.baseline:
        emitted = emit_baseline(descriptor, args.changelog)
    else:
        plan = plan_release(descriptor, previous)
        print(plan.report())
        if plan.is_noop:
            return EXIT_OK
        emitted = emit(plan, args.changelog)
        for line in record_taken(args.model, plan.changes):
            print(f"занято навсегда: {line}")
        # Перечень занятых номеров пополнен — дескриптор пересобирается, чтобы выпущенный
        # файл содержал закрытые номера. На хеш это не влияет: taken в него не входит.
        descriptor = _descriptor(args)

    args.releases.mkdir(parents=True, exist_ok=True)
    (args.releases / f"{descriptor['version']}.json").write_text(
        dump_descriptor(descriptor), encoding="utf-8"
    )
    registry.record(args.changelog, descriptor, emitted.files)
    for path in emitted.files:
        print(f"выпущено: {path}")
    return EXIT_OK


def _checks(args: argparse.Namespace) -> int:
    for check in checks_for(_descriptor(args)):
        print(f"-- {check.name}: {check.subject}\n{check.sql}\n")
    return EXIT_OK


def _intent_run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    created = not args.runs.exists()
    try:
        outcome = run_cycle(
            scenario,
            steps_for(scenario),
            runs_dir=args.runs,
            max_iterations=args.max_iterations,
        )
    except EnvironmentFault:
        raise
    except ModelError as error:
        # Отказ модели движок не порождает: всё, что он поднимает, — сбой процесса цикла.
        raise EnvironmentFault(str(error)) from error
    finally:
        if created and args.runs.exists():
            _recommend_ignore(args.runs)

    print(f"{outcome.code}  {outcome.state.title}: {outcome.reason}")
    print(f"итераций засчитано: {outcome.iterations}")
    for path in outcome.reports:
        print(f"отчёт: {path}")
    return EXIT_OK if outcome.closed else EXIT_REJECTED


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


def _norms(args: argparse.Namespace) -> int:
    print(delivery.rule(args.rule) if args.rule else delivery.norms(), end="")
    return EXIT_OK


def _sample(args: argparse.Namespace) -> int:
    print(delivery.sample(), end="")
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    import psycopg

    descriptor = _descriptor(args)
    problems = [f"changelog: {item}" for item in registry.verify_immutability(args.changelog)]

    try:
        connection = psycopg.connect(args.dsn, autocommit=True)
    except psycopg.OperationalError as error:
        raise EnvironmentFault(f"хранилище недоступно: {error}".strip(), where="verify") from error

    with connection:

        def fetch(sql: str) -> list[tuple[Any, ...]]:
            return connection.execute(sql).fetchall()

        problems += [f"схема: {drift}" for drift in verify_schema(descriptor, fetch)]
        problems += [
            f"целостность: {violation}" for violation in run_checks(checks_for(descriptor), fetch)
        ]

    if not problems:
        print(f"схема соответствует модели {descriptor['version']}")
        return EXIT_OK
    for problem in problems:
        print(f"РАСХОЖДЕНИЕ  {problem}", file=sys.stderr)
    return EXIT_REJECTED
