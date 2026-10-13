"""Тест архитектуры ядра: направление зависимостей, форма сценариев, неизменяемость домена.

Признаки соответствия APB-004..006 проверяются разбором исходников модулем `ast`, а не чтением
кода: тест не импортирует пакет и не требует новых зависимостей. Правила раскладки — design D1,
D2 и D11 change `layer-forge-core`:

- зависимости направлены внутрь: домен → стандартная библиотека и домен контракта модели,
  слой приложения → свой домен, свой слой и домен контракта модели, инфраструктура → свой
  модуль, домен контракта модели и `errors`; межмодульные зависимости идут только к домену
  контракта модели (CLAR-023);
- `yaml` и `psycopg` импортирует только инфраструктура;
- вход ядра зависит от контрактов сценариев, `errors` и точки сборки, а импортирует его только
  точка запуска;
- файл сценария — одна единица: контракт сценария, реализация, входной и выходной контракты;
- у реализации одна публичная операция `execute`, зависимости — контракты через конструктор;
- входной и выходной контракты неизменяемы и без методов, выходной не несёт объектов домена;
- классы домена с `@dataclass` неизменяемы;
- сценарии-запросы не получают контракт записи.

Самопроверки в конце файла прогоняют те же правила на подставных модулях: тест, который
не замечает нарушения, хуже отсутствующего теста.
"""

import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SOURCES = REPO / "plugin" / "forge" / "src"
PACKAGE = SOURCES / "forge_model"
GLOSSARY = REPO / "plugin" / "forge" / "share" / "docs" / "glossary.md"

#: Доменные модули ядра. Тест обходит весь пакет; перечень нужен, чтобы заметить модуль,
#: появившийся вне раскладки или исчезнувший из неё.
MODULES = frozenset({"contract", "release", "store", "intent", "delivery"})

SHARED_DOMAIN = "forge_model.contract.domain"
ERRORS = "forge_model.errors"
ASSEMBLY = "forge_model.assembly"
ENTRY = "forge_model.cli"
LAUNCH = "forge_model.__main__"

#: Сторонние библиотеки, разрешённые только инфраструктуре: разбор YAML и доступ к хранилищу.
INFRASTRUCTURE_LIBRARIES = frozenset({"yaml", "psycopg"})

#: Сценарии-команды. Остальные сценарии — запросы: контракт записи они не получают.
COMMANDS = frozenset({"ReleaseModel", "ReleaseBaseline", "RunIntent"})

#: Роль файла верхнего уровня пакета.
TOP_LEVEL = {"cli": "entry", "assembly": "assembly", "errors": "errors", "__main__": "launch"}


@dataclass(frozen=True)
class Unit:
    """Файл ядра: имя модуля, признак пакета и разобранный исходник."""

    name: str
    is_package: bool
    tree: ast.Module
    path: str

    @property
    def module(self) -> str | None:
        """Доменный модуль, которому принадлежит файл; `None` — файл верхнего уровня."""
        return _module_of(self.name, self.is_package)

    @property
    def layer(self) -> str:
        """Слой файла внутри доменного модуля либо роль файла верхнего уровня."""
        return _layer_of(self.name, self.is_package)


def _module_of(name: str, is_package: bool) -> str | None:
    parts = name.split(".")[1:]
    if not parts or (len(parts) == 1 and not is_package):
        return None
    return parts[0]


def _layer_of(name: str, is_package: bool) -> str:
    parts = name.split(".")[1:]
    if not parts:
        return "package"
    if len(parts) == 1:
        return "package" if is_package else TOP_LEVEL.get(parts[0], "unknown")
    return parts[1]


def _unit(path: Path) -> Unit:
    parts = list(path.relative_to(SOURCES).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return Unit(".".join(parts), is_package, tree, path.relative_to(REPO).as_posix())


def _package() -> list[Unit]:
    return [_unit(path) for path in sorted(PACKAGE.rglob("*.py"))]


def _checked(units: list[Unit]) -> list[Unit]:
    """Файлы, подлежащие проверке: весь пакет ядра."""
    return units


# --- зависимости ----------------------------------------------------------


def _imports(unit: Unit, known: frozenset[str]) -> Iterator[tuple[str, int]]:
    """Абсолютные имена импортируемых модулей с номером строки, включая импорты в функциях."""
    for node in ast.walk(unit.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = unit.name.split(".") if unit.is_package else unit.name.split(".")[:-1]
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, *([node.module] if node.module else [])])
            else:
                target = node.module or ""
            for alias in node.names:
                submodule = f"{target}.{alias.name}"
                yield (submodule if submodule in known else target), node.lineno


def _internal_allowed(unit: Unit, target: str) -> bool:
    target_module = _module_of(target, is_package=False)
    target_layer = _layer_of(target, is_package=False)
    layer, own = unit.layer, unit.module
    if layer == "domain":
        return target == SHARED_DOMAIN and own != "contract"
    if layer == "application":
        same = target_module == own and target_layer in {"domain", "application"}
        return same or target == SHARED_DOMAIN
    if layer == "infrastructure":
        same = target_module == own and target_layer in {"domain", "application", "infrastructure"}
        return same or target in {SHARED_DOMAIN, ERRORS}
    if layer == "entry":
        return target in {ERRORS, ASSEMBLY} or (
            target_module is not None and target_layer == "application"
        )
    if layer == "assembly":
        return target not in {ENTRY, LAUNCH}
    if layer == "launch":
        return target == ENTRY
    return False


def import_violations(unit: Unit, known: frozenset[str]) -> list[str]:
    """Импорты, направленные из внутреннего слоя во внешний или в чужой модуль."""
    found: list[str] = []
    if unit.layer not in {
        "domain",
        "application",
        "infrastructure",
        "package",
        *TOP_LEVEL.values(),
    }:
        found.append(f"{unit.path}: файл вне раскладки — слой {unit.layer!r} не известен")
    for target, line in _imports(unit, known):
        top = target.split(".")[0]
        if top == "forge_model":
            allowed = _internal_allowed(unit, target)
        elif top == "__future__" or top in sys.stdlib_module_names:
            allowed = True
        else:
            allowed = unit.layer == "infrastructure" and top in INFRASTRUCTURE_LIBRARIES
        if not allowed:
            found.append(f"{unit.path}:{line}: слой {unit.layer} импортирует {target}")
    return found


# --- форма компонентов ----------------------------------------------------


def _dataclass_flags(cls: ast.ClassDef) -> dict[str, bool] | None:
    """Ключи декоратора `@dataclass` со значением `True`; `None` — класс не dataclass."""
    for decorator in cls.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name != "dataclass":
            continue
        keywords = call.keywords if call else []
        return {
            str(keyword.arg): isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in keywords
        }
    return None


def _is_protocol(cls: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id == "Protocol")
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in cls.bases
    )


def _methods(cls: ast.ClassDef) -> list[str]:
    return [
        node.name for node in cls.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _annotation_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)} | {
        child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)
    }


def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def protocols(tree: ast.Module) -> set[str]:
    """Имена контрактов — классов `Protocol` — объявленных в файле."""
    return {name for name, cls in _classes(tree).items() if _is_protocol(cls)}


def _domain_names(unit: Unit, known: frozenset[str]) -> set[str]:
    """Имена, импортированные файлом из доменов."""
    names: set[str] = set()
    for node in ast.walk(unit.tree):
        if isinstance(node, ast.ImportFrom):
            for target, _ in _imports(
                Unit(unit.name, unit.is_package, ast.Module([node], []), unit.path), known
            ):
                if _layer_of(target, is_package=False) == "domain":
                    names |= {alias.asname or alias.name for alias in node.names}
    return names


def scenario_violations(
    unit: Unit, contracts: set[str], write_contracts: set[str], known: frozenset[str]
) -> list[str]:
    """Нарушения формы сценария в файле `application/<сценарий>.py`."""
    classes = {name: cls for name, cls in _classes(unit.tree).items() if not name.startswith("_")}
    interfaces = [name for name in classes if name.endswith("UseCaseInterface")]
    if len(interfaces) != 1:
        return [f"{unit.path}: файл сценария объявляет контрактов сценария: {len(interfaces)}"]
    stem = interfaces[0].removesuffix("UseCaseInterface")
    interface, case = classes[interfaces[0]], classes.get(f"{stem}UseCase")
    request, response = classes.get(f"{stem}Input"), classes.get(f"{stem}Output")
    expected = {f"{stem}UseCaseInterface", f"{stem}UseCase", f"{stem}Input", f"{stem}Output"}
    found: list[str] = []
    if set(classes) != expected:
        found.append(
            f"{unit.path}: сценарий {stem} — классы {sorted(classes)} вместо {sorted(expected)}"
        )
    if not _is_protocol(interface) or _methods(interface) != ["execute"]:
        found.append(
            f"{unit.path}: контракт {interface.name} — не Protocol с одной операцией execute"
        )
    for contract in (request, response):
        if contract is None:
            continue
        flags = _dataclass_flags(contract) or {}
        if not (flags.get("frozen") and flags.get("slots")):
            found.append(f"{unit.path}: {contract.name} — не @dataclass(frozen=True, slots=True)")
        if _methods(contract):
            found.append(f"{unit.path}: {contract.name} несёт методы {_methods(contract)}")
    if response is not None:
        leaked = _domain_names(unit, known) & set().union(
            *(
                _annotation_names(node.annotation)
                for node in response.body
                if isinstance(node, ast.AnnAssign)
            )
        )
        if leaked:
            found.append(f"{unit.path}: {response.name} несёт объекты домена {sorted(leaked)}")
    if case is not None:
        public = [name for name in _methods(case) if not name.startswith("_")]
        if public != ["execute"]:
            found.append(f"{unit.path}: {case.name} — публичные операции {public} вместо execute")
        found += _constructor_violations(unit, case, stem, contracts, write_contracts)
    return found


def _constructor_violations(
    unit: Unit, case: ast.ClassDef, stem: str, contracts: set[str], write_contracts: set[str]
) -> list[str]:
    init = next(
        (
            node
            for node in case.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ),
        None,
    )
    if init is None:
        return []
    found: list[str] = []
    for argument in [*init.args.args[1:], *init.args.kwonlyargs]:
        names = _annotation_names(argument.annotation)
        if not names or not names <= contracts | write_contracts:
            found.append(
                f"{unit.path}: {case.name} получает {argument.arg} не через контракт: "
                f"{sorted(names)}"
            )
        if stem not in COMMANDS and names & write_contracts:
            found.append(f"{unit.path}: сценарий-запрос {case.name} получает контракт записи")
    return found


def domain_violations(unit: Unit) -> list[str]:
    """Классы домена с `@dataclass`, не объявленные неизменяемыми."""
    found: list[str] = []
    for cls in _classes(unit.tree).values():
        flags = _dataclass_flags(cls)
        if flags is not None and not flags.get("frozen"):
            found.append(f"{unit.path}: класс домена {cls.name} изменяем — нужен frozen=True")
    return found


def discrepancy_violations(unit: Unit) -> list[str]:
    """Модель расхождения модуля: та же форма из двух полей, что у остальных модулей."""
    cls = _classes(unit.tree).get("Discrepancy")
    if cls is None:
        return []
    fields = [
        node.target.id
        for node in cls.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    flags = _dataclass_flags(cls) or {}
    if fields != ["place", "message"] or not flags.get("frozen"):
        return [f"{unit.path}: Discrepancy — поля {fields}, ожидаются неизменяемые place и message"]
    return []


def violations(units: list[Unit], checked: list[Unit]) -> list[str]:
    """Все нарушения раскладки в проверяемых файлах."""
    known = frozenset(unit.name for unit in units)
    write_contracts = set().union(
        *(protocols(unit.tree) for unit in units if unit.layer == "domain")
    )
    found: list[str] = []
    for unit in checked:
        found += import_violations(unit, known)
        if unit.layer == "domain":
            found += domain_violations(unit)
        if unit.layer != "application" or unit.is_package:
            continue
        if unit.name.endswith(".contracts"):
            found += discrepancy_violations(unit)
            continue
        own = set().union(
            *(
                protocols(other.tree)
                for other in units
                if other.module == unit.module and other.name.endswith(".application.contracts")
            )
        )
        found += scenario_violations(unit, own, write_contracts, known)
    return found


def test_раскладка_ядра_соблюдает_правила_слоёв():
    units = _package()

    assert violations(units, _checked(units)) == []


def test_пакет_разложен_по_доменным_модулям():
    """Верхний уровень пакета — доменные модули и файлы входа, технических слоёв нет."""
    units = _package()

    assert {unit.module for unit in units} - {None} == MODULES
    assert {unit.name for unit in units if unit.module is None} == {
        "forge_model",
        "forge_model.__main__",
        "forge_model.assembly",
        "forge_model.cli",
        "forge_model.errors",
    }


def test_правило_структуры_вызывается_только_из_компиляции():
    """APB-004 (8): правило структуры живёт в одной точке домена, обойти его нельзя."""
    calls = sorted(
        (unit.name, function.name)
        for unit in _package()
        for function in ast.walk(unit.tree)
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _annotation_names(node.func) & {"structure_findings"}
    )
    imported = [
        unit.name
        for unit in _package()
        for node in ast.walk(unit.tree)
        if isinstance(node, ast.ImportFrom)
        and "structure_findings" in {alias.name for alias in node.names}
    ]

    assert calls == [("forge_model.contract.domain", "compile_descriptor")]
    assert imported == []


def test_контракт_записи_принимает_один_агрегат():
    """APB-005 (1), CLAR-003: в контракте записи одна операция, и она принимает агрегат целиком."""
    found = []
    for unit in _package():
        if unit.layer != "domain":
            continue
        aggregates = set(immutable_classes(unit))
        for name in protocols(unit.tree):
            methods = [
                node for node in _classes(unit.tree)[name].body if isinstance(node, ast.FunctionDef)
            ]
            found += [
                (
                    name,
                    method.name,
                    [_annotation_names(arg.annotation) for arg in method.args.args[1:]],
                )
                for method in methods
            ]
            for method in methods:
                arguments = method.args.args[1:]
                assert method.name == "add", f"{name}.{method.name}: в контракте записи только add"
                assert len(arguments) == 1, f"{name}.add принимает не один агрегат"
                assert _annotation_names(arguments[0].annotation) <= aggregates

    assert found == [("ReleaseRepository", "add", [{"Release"}])]


def concepts(glossary: str) -> set[str]:
    """Английские имена понятий глоссария без пробелов; у множественного — и единственное."""
    names: set[str] = set()
    for english in re.findall(r"^\| [^|]+? \(([A-Z][A-Za-z ]+)\) \|", glossary, re.MULTILINE):
        name = english.replace(" ", "")
        names.add(name)
        if name.endswith("es"):
            names.add(name[:-2])
        if name.endswith("s"):
            names.add(name[:-1])
    return names


def _is_enum(cls: ast.ClassDef) -> bool:
    return any(
        isinstance(base, ast.Attribute)
        and base.attr == "Enum"
        and isinstance(base.value, ast.Name)
        and base.value.id == "enum"
        for base in cls.bases
    )


def immutable_classes(unit: Unit) -> list[str]:
    """Неизменяемые классы файла: `@dataclass(frozen=True)` и перечисления `enum.Enum`."""
    return [
        cls.name
        for cls in _classes(unit.tree).values()
        if (_dataclass_flags(cls) or {}).get("frozen") or _is_enum(cls)
    ]


def test_имена_домена_совпадают_с_глоссарием():
    """APB-006 (5), D10: у каждого неизменяемого класса домена есть понятие глоссария."""
    known = concepts(GLOSSARY.read_text(encoding="utf-8"))
    unnamed = [
        f"{unit.path}: {name}"
        for unit in _package()
        if unit.layer == "domain"
        for name in immutable_classes(unit)
        if name not in known
    ]

    assert unnamed == []


def test_самопроверка_имён_ловит_класс_без_понятия():
    unit = _synthetic(
        "forge_model.demo.domain",
        "import enum\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True)\n"
        "class IntegrityCheck:\n    name: str\n\n\nclass Mood(enum.Enum):\n    CALM = 1\n",
    )
    known = concepts("| Запросы целостности (Integrity Checks) | ... |\n")

    assert immutable_classes(unit) == ["IntegrityCheck", "Mood"]
    assert [name for name in immutable_classes(unit) if name not in known] == ["Mood"]


# --- самопроверки ---------------------------------------------------------


def _synthetic(name: str, source: str, *, is_package: bool = False) -> Unit:
    return Unit(name, is_package, ast.parse(source), name.replace(".", "/") + ".py")


DEMO_CONTRACTS = """
from typing import Protocol


class Store(Protocol):
    def read(self) -> str: ...
"""

DEMO_SCENARIO = """
from dataclasses import dataclass
from typing import Protocol

from .contracts import Store


@dataclass(frozen=True, slots=True)
class MakeDemoInput:
    name: str


@dataclass(frozen=True, slots=True)
class MakeDemoOutput:
    text: str


class MakeDemoUseCaseInterface(Protocol):
    def execute(self, request: MakeDemoInput) -> MakeDemoOutput: ...


class MakeDemoUseCase:
    def __init__(self, store: Store) -> None:
        self._store = store

    def execute(self, request: MakeDemoInput) -> MakeDemoOutput:
        return MakeDemoOutput(self._store.read() + request.name)
"""


def _demo(scenario: str = DEMO_SCENARIO, domain: str = "") -> list[str]:
    units = [
        _synthetic("forge_model.demo", "", is_package=True),
        _synthetic("forge_model.demo.domain", domain),
        _synthetic("forge_model.demo.application", "", is_package=True),
        _synthetic("forge_model.demo.application.contracts", DEMO_CONTRACTS),
        _synthetic("forge_model.demo.application.make_demo", scenario),
    ]
    return violations(units, units)


def test_самопроверка_правильный_модуль_проходит():
    assert _demo() == []


@pytest.mark.parametrize(
    "domain",
    [
        "import yaml\n",
        "from .infrastructure import Files\n",
        "from .application.contracts import Store\n",
        "from forge_model.errors import EnvironmentFault\n",
        "from forge_model.release.domain import Release\n",
    ],
    ids=["yaml", "инфраструктура", "приложение", "errors", "чужой домен"],
)
def test_самопроверка_ловит_запрещённый_импорт(domain):
    assert any("импортирует" in item for item in _demo(domain=domain))


def test_самопроверка_ловит_изменяемый_входной_контракт():
    scenario = DEMO_SCENARIO.replace(
        "@dataclass(frozen=True, slots=True)\nclass MakeDemoInput",
        "@dataclass\nclass MakeDemoInput",
    )

    assert any("MakeDemoInput — не @dataclass" in item for item in _demo(scenario))


def test_самопроверка_ловит_вторую_публичную_операцию():
    scenario = DEMO_SCENARIO + "\n    def undo(self) -> None:\n        pass\n"

    assert any("публичные операции ['execute', 'undo']" in item for item in _demo(scenario))


DEMO_VALUE = """
from dataclasses import dataclass


@dataclass{flags}
class Thing:
    value: int
"""

DEMO_REPOSITORY = """
from typing import Protocol


class DemoRepository(Protocol):
    def add(self, item: str) -> None: ...
"""


def test_самопроверка_ловит_логику_в_контракте_и_домен_в_выходе():
    scenario = DEMO_SCENARIO.replace(
        "    text: str\n", "    text: Thing\n\n    def size(self) -> int:\n        return 1\n"
    ).replace(
        "from .contracts import Store", "from .contracts import Store\nfrom ..domain import Thing"
    )

    found = _demo(scenario, domain=DEMO_VALUE.format(flags="(frozen=True)"))
    assert any("MakeDemoOutput несёт методы" in item for item in found)
    assert any("MakeDemoOutput несёт объекты домена ['Thing']" in item for item in found)


def test_самопроверка_ловит_изменяемый_класс_домена_и_зависимость_не_через_контракт():
    scenario = DEMO_SCENARIO.replace("store: Store", "store: dict")

    found = _demo(scenario, domain=DEMO_VALUE.format(flags=""))
    assert any("класс домена Thing изменяем" in item for item in found)
    assert any("получает store не через контракт" in item for item in found)


def test_самопроверка_ловит_контракт_записи_в_запросе():
    scenario = DEMO_SCENARIO.replace(
        "from .contracts import Store",
        "from .contracts import Store\nfrom ..domain import DemoRepository",
    ).replace("store: Store", "store: DemoRepository")

    assert any(
        "сценарий-запрос MakeDemoUseCase получает контракт записи" in item
        for item in _demo(scenario, DEMO_REPOSITORY)
    )
