"""Домен контракта модели: модель, правило структуры, дескриптор, дельта и гейт совместимости.

Домен держит правила предмета и ничего не знает о файлах и формате их записи. Объекты модели
строит инфраструктура; домен проверяет их одним правилом структуры, компилирует в дескриптор,
сравнивает версии и решает, можно ли выпускать (design D4–D6 change `layer-forge-core`).

Межмодульные зависимости ядра идут только сюда: выпуск, хранилище и цикл намерения получают
дескриптор как объект этого домена (CLAR-023). Поэтому здесь же живёт гейт совместимости:
его решение печатает и сравнение версий, и выпуск, а модуль контракта от модуля выпуска
не зависит.

Каждый элемент модели знает своё место — файл и строку. Место не входит ни в равенство
элементов, ни в дескриптор: оно нужно только затем, чтобы нарушение называло строку файла.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from typing import Any, Final

#: Скалярные типы поля (MDL-011).
SCALAR_TYPES: Final = ("text", "int", "bool", "timestamp", "uuid")
#: Виды типа поля: скаляр, ссылка на перечисление, ссылка на тип узла.
SCALAR: Final = "scalar"
ENUM: Final = "enum"
REF: Final = "ref"

#: Формы записи кода типа (MDL-006), имени поля и связи (MDL-010), имени значения
#: перечисления (MDL-005). Выражения перенесены из разбора модели как есть, вместе
#: с расхождением Р6 приёмочного отчёта: цифры в именах допускаются.
CODE_RE: Final = re.compile(r"^[A-Z]{2,10}$")
NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_]*$")
ENUM_VALUE_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")

CODE_FORM: Final = "2-10 заглавных латинских букв"
NAME_FORM: Final = "строчными латинскими с подчёркиваниями"
ENUM_VALUE_FORM: Final = "ЗАГЛАВНЫМИ_С_ПОДЧЁРКИВАНИЕМ"


# --- место и нарушение ----------------------------------------------------


@dataclass(frozen=True)
class Place:
    """Место в модели: файл от каталога модели и строка, считая с единицы.

    Строки нет там, где её не к чему привязать: файл не найден или пуст.
    """

    file: str
    line: int | None = None

    def __str__(self) -> str:
        return self.file if self.line is None else f"{self.file}:{self.line}"


#: Место элемента, построенного не из файла: например, прочитанного из выпущенного дескриптора.
NOWHERE: Final = Place("")


@dataclass(frozen=True)
class Finding:
    """Нарушение: место, элемент модели и что с ним не так."""

    place: Place
    element: str
    message: str


def _by_place(finding: Finding) -> tuple[str, int]:
    return finding.place.file, finding.place.line or 0


# --- модель ---------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Version:
    """Версия модели: старший разряд — контракт, средний — структура, младший — описания."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: object) -> Version | None:
    """Версия из записи `X.Y.Z` (MDL-004); `None` — запись не этого вида."""
    if not isinstance(text, str):
        return None
    parts = text.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return Version(int(parts[0]), int(parts[1]), int(parts[2]))


@dataclass(frozen=True)
class TakenNumbers:
    """Занятые навсегда номера, имена и коды (MDL-016). Пополняется инструментом."""

    fields: tuple[int, ...] = ()
    names: tuple[str, ...] = ()
    codes: tuple[int, ...] = ()


@dataclass(frozen=True)
class Field:
    """Поле типа узла. Идентичность — номер (MDL-009), имя может меняться.

    Тип поля записан видом и именем: скаляр `text`, перечисление `enum.<имя>`, ссылка на тип
    узла `ref.<ТИП>` (MDL-011). В дескрипторе `required_since` раскрыт: обязательное поле
    без признака обязательно с нулевого среднего разряда.
    """

    id: int
    name: str
    kind: str
    type: str
    required: bool = False
    required_since: int | None = None
    #: Описание переносится в дескриптор как записано в модели.
    description: object = None
    place: Place = dc_field(default=NOWHERE, compare=False)

    @property
    def column(self) -> str:
        """Колонка таблицы ревизий — имя поля."""
        return self.name

    @property
    def type_text(self) -> str:
        """Тип поля в записи модели."""
        return self.type if self.kind == SCALAR else f"{self.kind}.{self.type}"


@dataclass(frozen=True)
class NodeType:
    """Тип узла графа: бизнес-требование, функциональное требование, задача и прочие."""

    id: int
    code: str
    name_ru: str
    name_en: str
    fields: tuple[Field, ...]
    taken: TakenNumbers = TakenNumbers()
    description: object = None
    place: Place = dc_field(default=NOWHERE, compare=False)

    @property
    def table(self) -> str:
        """Имя таблицы ревизий, выводимое из кода типа (MDL-006)."""
        return f"{self.code.lower()}_revision"

    @property
    def code_pattern(self) -> str:
        """Форма кода экземпляра типа."""
        return f"{self.code}-{{NNN}}"


@dataclass(frozen=True)
class EnumValue:
    """Значение перечисления: номер неизменен, имя может меняться (MDL-005)."""

    id: int
    name: str
    place: Place = dc_field(default=NOWHERE, compare=False)


@dataclass(frozen=True)
class Enum:
    """Перечисление: именованный набор значений с номерами."""

    id: int
    name: str
    values: tuple[EnumValue, ...]
    taken: TakenNumbers = TakenNumbers()
    place: Place = dc_field(default=NOWHERE, compare=False)


@dataclass(frozen=True)
class Cardinality:
    """Границы числа связей. `max = None` — верхней границы нет (MDL-014)."""

    min: int = 0
    max: int | None = None


@dataclass(frozen=True)
class RelationSignature:
    """Сигнатура связи: между какими типами связь допустима и в каком числе (MDL-013)."""

    id: int
    name: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    source_cardinality: Cardinality = Cardinality()
    target_cardinality: Cardinality = Cardinality()
    acyclic: bool = True
    description: object = None
    place: Place = dc_field(default=NOWHERE, compare=False)


@dataclass(frozen=True)
class Model:
    """Модель одной версии: перечисления, типы узлов и сигнатуры связей.

    Модель — то, что записано в файлах: она может нарушать правила структуры. Место модели —
    объявление версии в манифесте: к нему относятся решения гейта совместимости.
    """

    package: str
    version: Version
    enums: tuple[Enum, ...] = ()
    types: tuple[NodeType, ...] = ()
    relations: tuple[RelationSignature, ...] = ()
    place: Place = dc_field(default=NOWHERE, compare=False)


@dataclass(frozen=True)
class ModelReading:
    """Прочитанная модель и нарушения формата файлов.

    Модель есть, если формат позволил построить её объекты; значения при этом могут нарушать
    правила структуры. Модели нет, если не прочитан манифест: без имени и версии собирать
    нечего, но нарушения остальных файлов всё равно названы.
    """

    model: Model | None
    findings: tuple[Finding, ...] = ()


# --- правило структуры ----------------------------------------------------


def structure_findings(model: Model) -> tuple[Finding, ...]:
    """Все нарушения правил структуры модели — единственное правило, без вариантов.

    Правило проверяет формы кодов и имён (MDL-005, MDL-006, MDL-010), уникальность номеров
    и имён, пересечение с занятыми номерами и ссылки на типы и перечисления. Вызывается только
    из `compile_descriptor`: подкоманда, собирающая модель, обойти его не может (APB-004 (8)).
    Сравнение с выпущенной версией — не здесь, а в гейте совместимости: для него нужны две
    версии.
    """
    found: list[Finding] = []
    found += _duplicates(model.types, lambda item: item.id, "номер типа", _type_element)
    found += _duplicates(model.types, lambda item: item.code, "код типа", _type_element)
    found += _duplicates(model.enums, lambda item: item.id, "номер перечисления", _enum_element)
    found += _duplicates(model.relations, lambda item: item.id, "номер связи", _relation_element)
    found += _duplicates(model.relations, lambda item: item.name, "имя связи", _relation_element)
    for enum_ in model.enums:
        found += _enum_findings(enum_)
    for node in model.types:
        found += _type_findings(model, node)
    codes = {node.code for node in model.types}
    for relation in model.relations:
        found += _form(
            relation.name, NAME_RE, NAME_FORM, relation.place, _relation_element(relation)
        )
        for code in relation.sources + relation.targets:
            if code not in codes:
                found.append(
                    Finding(
                        relation.place,
                        _relation_element(relation),
                        f"ссылка на несуществующий тип узла {code!r}",
                    )
                )
    return tuple(found)


def _type_element(node: NodeType) -> str:
    return f"тип {node.code}"


def _field_element(node: NodeType, item: Field) -> str:
    return f"тип {node.code}, поле {item.id} ({item.name})"


def _enum_element(enum_: Enum, value: EnumValue | None = None) -> str:
    element = f"перечисление {enum_.name}"
    return element if value is None else f"{element}, значение {value.id} ({value.name})"


def _relation_element(relation: RelationSignature) -> str:
    return f"связь {relation.name}"


def _form(
    value: str, form: re.Pattern[str], expectation: str, place: Place, element: str
) -> list[Finding]:
    if form.match(value):
        return []
    return [Finding(place, element, f"значение {value!r} должно записываться {expectation}")]


def _duplicates[Item: (NodeType, Field, Enum, EnumValue, RelationSignature)](
    items: Iterable[Item],
    key: Callable[[Item], Hashable],
    subject: str,
    element: Callable[[Item], str],
) -> list[Finding]:
    """Повторы ключа: нарушение называет каждое повторное появление, а не первое."""
    seen: set[Hashable] = set()
    found: list[Finding] = []
    for item in items:
        value = key(item)
        if value in seen:
            found.append(
                Finding(item.place, element(item), f"{subject} {value!r} встречается дважды")
            )
        seen.add(value)
    return found


def _taken[Item: (Field, EnumValue)](
    items: Iterable[Item],
    key: Callable[[Item], Hashable],
    occupied: Iterable[Hashable],
    subject: str,
    element: Callable[[Item], str],
) -> list[Finding]:
    """Значения, числящиеся занятыми навсегда (MDL-016)."""
    taken = set(occupied)
    return [
        Finding(
            item.place,
            element(item),
            f"{subject} {key(item)!r} числится занятым и не может быть выдан повторно",
        )
        for item in items
        if key(item) in taken
    ]


def _enum_findings(enum_: Enum) -> list[Finding]:
    def element(value: EnumValue) -> str:
        return _enum_element(enum_, value)

    found: list[Finding] = []
    for value in enum_.values:
        found += _form(value.name, ENUM_VALUE_RE, ENUM_VALUE_FORM, value.place, element(value))
    found += _duplicates(enum_.values, lambda value: value.id, "номер значения", element)
    found += _duplicates(enum_.values, lambda value: value.name, "имя значения", element)
    found += _taken(
        enum_.values, lambda value: value.id, enum_.taken.fields, "номер значения", element
    )
    found += _taken(
        enum_.values, lambda value: value.name, enum_.taken.names, "имя значения", element
    )
    return found


def _type_findings(model: Model, node: NodeType) -> list[Finding]:
    def element(item: Field) -> str:
        return _field_element(node, item)

    found = _form(node.code, CODE_RE, CODE_FORM, node.place, _type_element(node))
    for item in node.fields:
        found += _form(item.name, NAME_RE, NAME_FORM, item.place, element(item))
    found += _duplicates(node.fields, lambda item: item.id, "номер поля", element)
    found += _duplicates(node.fields, lambda item: item.name, "имя поля", element)
    found += _taken(node.fields, lambda item: item.id, node.taken.fields, "номер поля", element)
    found += _taken(node.fields, lambda item: item.name, node.taken.names, "имя поля", element)

    enums = {enum_.name for enum_ in model.enums}
    codes = {other.code for other in model.types}
    for item in node.fields:
        if item.kind == ENUM and item.type not in enums:
            found.append(
                Finding(
                    item.place,
                    element(item),
                    f"ссылка на несуществующее перечисление {item.type!r}",
                )
            )
        if item.kind == REF and item.type not in codes:
            found.append(
                Finding(
                    item.place, element(item), f"ссылка на несуществующий тип узла {item.type!r}"
                )
            )
        if item.required_since is not None and item.required_since > model.version.minor:
            found.append(
                Finding(
                    item.place,
                    element(item),
                    f"required_since {item.required_since} больше текущего среднего разряда "
                    f"{model.version.minor}",
                )
            )
    return found


# --- дескриптор -----------------------------------------------------------


@dataclass(frozen=True)
class Descriptor:
    """Дескриптор — скомпилированный контракт модели одной версии.

    От модели дескриптор отличается тем, что в нём раскрыты умолчания, порядок элементов
    фиксирован номерами, а хеш посчитан. Его чтение не требует исходных файлов модели, поэтому
    именно он передаётся потребителям и между модулями ядра.

    Занятые номера лежат при своих элементах — типах и перечислениях, — как в файле
    дескриптора; старший разряд выводится из версии. Место дескриптора — объявление версии
    в манифесте рабочей модели; у прочитанного выпущенного дескриптора места нет.
    """

    model: str
    version: Version
    enums: tuple[Enum, ...]
    types: tuple[NodeType, ...]
    relations: tuple[RelationSignature, ...]
    hash: str
    place: Place = dc_field(default=NOWHERE, compare=False)

    @property
    def major(self) -> int:
        """Старший разряд версии: имя каталога модели (MDL-002)."""
        return self.version.major

    def type_by_code(self, code: str) -> NodeType | None:
        return next((node for node in self.types if node.code == code), None)

    def enum_by_name(self, name: str) -> Enum | None:
        return next((enum_ for enum_ in self.enums if enum_.name == name), None)


@dataclass(frozen=True)
class Compilation:
    """Итог компиляции модели: дескриптор либо перечень всех нарушений."""

    descriptor: Descriptor | None
    findings: tuple[Finding, ...] = ()


#: Ключи канонической формы, не входящие в хеш (MDL-019): их изменение не меняет ни схему,
#: ни данные. Перечень занятых номеров исключён: он пополняется инструментом после подсчёта
#: дескриптора, иначе хеш модели разошёлся бы с хешем, записанным в хранилище замыкающей
#: миграцией. Номер версии исключён тоже: иначе случай «версию повысили, а модель не тронули»
#: был бы неотличим от изменения.
NON_STRUCTURAL: Final = frozenset(
    {"description", "name_ru", "name_en", "hash", "version", "major", "minor", "patch", "taken"}
)


def compile_descriptor(reading: ModelReading) -> Compilation:
    """Скомпилировать прочитанную модель в дескриптор.

    Правило структуры вызывается здесь и только здесь. При любом нарушении — формата
    или структуры — дескриптор не собирается, а нарушения возвращаются все разом, по порядку
    мест.
    """
    model = reading.model
    structure = structure_findings(model) if model is not None else ()
    findings = tuple(sorted((*reading.findings, *structure), key=_by_place))
    if model is None or findings:
        return Compilation(None, findings)
    draft = Descriptor(
        model=model.package,
        version=model.version,
        enums=tuple(
            replace(enum_, values=tuple(sorted(enum_.values, key=lambda value: value.id)))
            for enum_ in sorted(model.enums, key=lambda item: item.id)
        ),
        types=tuple(
            replace(node, fields=tuple(_expanded(item) for item in sorted(node.fields, key=_id)))
            for node in sorted(model.types, key=_id)
        ),
        relations=tuple(sorted(model.relations, key=lambda item: item.id)),
        hash="",
        place=model.place,
    )
    return Compilation(replace(draft, hash=descriptor_hash(descriptor_document(draft))))


def _id(item: NodeType | Field) -> int:
    return item.id


def _expanded(item: Field) -> Field:
    """Раскрыть умолчание: обязательное поле без признака обязательно с самого начала."""
    return replace(item, required_since=(item.required_since or 0) if item.required else None)


def canonical_json(value: Any) -> str:
    """Каноническое представление: отсортированные ключи, стабильные разделители."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def descriptor_hash(document: Mapping[str, Any]) -> str:
    """Хеш дескриптора по структурным элементам канонической формы (MDL-019)."""
    structural = canonical_json(_structural(document))
    return "sha256:" + hashlib.sha256(structural.encode("utf-8")).hexdigest()


def _structural(value: Any) -> Any:
    """Убрать из структуры всё, что не влияет ни на схему, ни на данные."""
    if isinstance(value, Mapping):
        return {key: _structural(item) for key, item in value.items() if key not in NON_STRUCTURAL}
    if isinstance(value, list):
        return [_structural(item) for item in value]
    return value


def descriptor_document(descriptor: Descriptor) -> dict[str, Any]:
    """Каноническая форма дескриптора — часть контракта хеша, а не формат хранения.

    По ней считается хеш, и из неё же инфраструктура пишет файл выпущенной версии: обе стороны
    видят одну форму, поэтому байты файла не зависят от того, как устроены объекты домена.
    """
    return {
        "model": descriptor.model,
        "version": str(descriptor.version),
        "major": descriptor.version.major,
        "minor": descriptor.version.minor,
        "patch": descriptor.version.patch,
        "enums": [_enum_document(enum_) for enum_ in descriptor.enums],
        "types": [_type_document(descriptor, node) for node in descriptor.types],
        "relations": [_relation_document(relation) for relation in descriptor.relations],
        "hash": descriptor.hash,
    }


def _enum_document(enum_: Enum) -> dict[str, Any]:
    return {
        "id": enum_.id,
        "name": enum_.name,
        "values": [{"id": value.id, "name": value.name} for value in enum_.values],
        "taken": _taken_document(enum_.taken),
    }


def _type_document(descriptor: Descriptor, node: NodeType) -> dict[str, Any]:
    return {
        "id": node.id,
        "code": node.code,
        "table": node.table,
        "code_pattern": node.code_pattern,
        "name_ru": node.name_ru,
        "name_en": node.name_en,
        "description": node.description,
        "fields": [_field_document(descriptor, item) for item in node.fields],
        "taken": _taken_document(node.taken),
    }


def _field_document(descriptor: Descriptor, item: Field) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": item.id,
        "name": item.name,
        "column": item.column,
        "kind": item.kind,
        "type": item.type,
        "required": item.required,
        "required_since": item.required_since,
        "description": item.description,
    }
    if item.kind == ENUM:
        enum_ = descriptor.enum_by_name(item.type)
        # Ссылку на несуществующее перечисление отвергает правило структуры, поэтому
        # у скомпилированного дескриптора перечисление есть всегда.
        entry["values"] = [value.name for value in enum_.values] if enum_ else []
    return entry


def _relation_document(relation: RelationSignature) -> dict[str, Any]:
    return {
        "id": relation.id,
        "name": relation.name,
        "from": list(relation.sources),
        "to": list(relation.targets),
        "from_cardinality": _cardinality_document(relation.source_cardinality),
        "to_cardinality": _cardinality_document(relation.target_cardinality),
        "acyclic": relation.acyclic,
        "description": relation.description,
    }


def _cardinality_document(cardinality: Cardinality) -> dict[str, Any]:
    return {"min": cardinality.min, "max": cardinality.max}


def _taken_document(taken: TakenNumbers) -> dict[str, Any]:
    return {"fields": list(taken.fields), "names": list(taken.names), "codes": list(taken.codes)}


# --- дельта ---------------------------------------------------------------


class OperationClass(enum.Enum):
    """Класс операции дельты (MDL-020): что печатается при выпуске, а не запрет."""

    SAFE = "safe"
    BREAKING = "breaking"
    DESTRUCTIVE = "destructive"

    @property
    def label(self) -> str:
        """Пояснение класса для вывода."""
        return _CLASS_LABELS[self]


_CLASS_LABELS: Final = {
    OperationClass.SAFE: "безопасно",
    OperationClass.BREAKING: "ломает контракт",
    OperationClass.DESTRUCTIVE: "удаляет данные",
}

SAFE: Final = OperationClass.SAFE
BREAKING: Final = OperationClass.BREAKING
DESTRUCTIVE: Final = OperationClass.DESTRUCTIVE

#: Виды операций дельты.
ENUM_ADDED: Final = "enum_added"
ENUM_REMOVED: Final = "enum_removed"
ENUM_VALUE_ADDED: Final = "enum_value_added"
ENUM_VALUE_RENAMED: Final = "enum_value_renamed"
ENUM_VALUE_REMOVED: Final = "enum_value_removed"
TYPE_ADDED: Final = "type_added"
TYPE_REMOVED: Final = "type_removed"
FIELD_ADDED: Final = "field_added"
FIELD_RENAMED: Final = "field_renamed"
FIELD_TYPE_CHANGED: Final = "field_type_changed"
FIELD_REQUIRED: Final = "field_required"
FIELD_REMOVED: Final = "field_removed"
RELATION_ADDED: Final = "relation_added"
RELATION_RENAMED: Final = "relation_renamed"
RELATION_CARDINALITY: Final = "relation_cardinality"
RELATION_REMOVED: Final = "relation_removed"


@dataclass(frozen=True)
class Operation:
    """Операция дельты в терминах модели: вид, элемент, класс и пояснение.

    Элементы, которых операция касается, переданы объектами дескриптора: поле — для операций
    над полями (`previous_field` — каким оно было), тип узла — для его добавления и удаления,
    значение — для операций над перечислением, сигнатура связи в новой версии и коды типов —
    для операций над связями.
    """

    kind: str
    element: str
    operation_class: OperationClass
    detail: str
    type_code: str = ""
    field: Field | None = None
    previous_field: Field | None = None
    node_type: NodeType | None = None
    enum_name: str = ""
    value: EnumValue | None = None
    relation: RelationSignature | None = None
    codes: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.element}: {self.detail} [{self.operation_class.label}]"


@dataclass(frozen=True)
class Delta:
    """Дельта — операции, переводящие выпущенную версию модели в рабочую."""

    operations: tuple[Operation, ...] = ()

    @property
    def warnings(self) -> tuple[Operation, ...]:
        """Операции, о которых выпуск предупреждает: ломающие контракт и разрушающие данные."""
        return tuple(item for item in self.operations if item.operation_class is not SAFE)


def diff(old: Descriptor, new: Descriptor) -> Delta:
    """Дельта перехода `old -> new`.

    Сравнение идёт по номерам элементов: имя и порядок на результат не влияют. Поэтому
    переименование опознаётся как переименование, а не как удаление одного поля и добавление
    другого, и данные не теряются.
    """
    return Delta(
        (
            *_diff_enums(old.enums, new.enums),
            *_diff_types(old.types, new.types),
            *_diff_relations(old.relations, new.relations),
        )
    )


def _by_id[Item: (Enum, EnumValue, NodeType, Field, RelationSignature)](
    items: Iterable[Item],
) -> dict[int, Item]:
    return {item.id: item for item in items}


def _diff_enums(old: Sequence[Enum], new: Sequence[Enum]) -> list[Operation]:
    found: list[Operation] = []
    old_map, new_map = _by_id(old), _by_id(new)

    for enum_id, entry in new_map.items():
        if enum_id not in old_map:
            found.append(Operation(ENUM_ADDED, entry.name, SAFE, "добавлено перечисление"))
            continue
        before, after = _by_id(old_map[enum_id].values), _by_id(entry.values)
        for value_id, value in after.items():
            if value_id not in before:
                found.append(
                    Operation(
                        ENUM_VALUE_ADDED,
                        f"{entry.name}.{value.name}",
                        SAFE,
                        f"добавлено значение {value.name}",
                        enum_name=entry.name,
                        value=value,
                    )
                )
            elif before[value_id].name != value.name:
                found.append(
                    Operation(
                        ENUM_VALUE_RENAMED,
                        f"{entry.name}.{value_id}",
                        SAFE,
                        f"значение {before[value_id].name} -> {value.name}",
                        enum_name=entry.name,
                        value=value,
                    )
                )
        for value_id, value in before.items():
            if value_id not in after:
                found.append(
                    Operation(
                        ENUM_VALUE_REMOVED,
                        f"{entry.name}.{value.name}",
                        BREAKING,
                        f"удалено значение {value.name}",
                        enum_name=entry.name,
                        value=value,
                    )
                )

    for enum_id, entry in old_map.items():
        if enum_id not in new_map:
            found.append(Operation(ENUM_REMOVED, entry.name, BREAKING, "удалено перечисление"))
    return found


def _diff_types(old: Sequence[NodeType], new: Sequence[NodeType]) -> list[Operation]:
    found: list[Operation] = []
    old_map, new_map = _by_id(old), _by_id(new)

    for type_id, entry in new_map.items():
        if type_id not in old_map:
            found.append(
                Operation(TYPE_ADDED, entry.code, SAFE, "добавлен тип узла", node_type=entry)
            )
            continue
        found += _diff_fields(old_map[type_id], entry)

    for type_id, entry in old_map.items():
        if type_id not in new_map:
            found.append(
                Operation(
                    TYPE_REMOVED,
                    entry.code,
                    DESTRUCTIVE,
                    f"удалён тип узла, таблица {entry.table} будет удалена вместе с данными",
                    node_type=entry,
                )
            )
    return found


def _diff_fields(old_type: NodeType, new_type: NodeType) -> list[Operation]:
    code = new_type.code
    found: list[Operation] = []
    before, after = _by_id(old_type.fields), _by_id(new_type.fields)

    for field_id, item in after.items():
        element = f"{code}.{field_id}"
        if field_id not in before:
            kind = BREAKING if item.required and not item.required_since else SAFE
            detail = f"добавлено поле {item.name}"
            if kind is BREAKING:
                detail += " как обязательное без required_since"
            found.append(Operation(FIELD_ADDED, element, kind, detail, type_code=code, field=item))
            continue

        was = before[field_id]
        if was.name != item.name:
            found.append(
                Operation(
                    FIELD_RENAMED,
                    element,
                    SAFE,
                    f"{was.name} -> {item.name}",
                    type_code=code,
                    field=item,
                    previous_field=was,
                )
            )
        if (was.kind, was.type) != (item.kind, item.type):
            found.append(
                Operation(
                    FIELD_TYPE_CHANGED,
                    element,
                    DESTRUCTIVE,
                    f"тип поля {item.name}: {was.type} -> {item.type}",
                    type_code=code,
                    field=item,
                    previous_field=was,
                )
            )
        if not was.required and item.required:
            since = (
                f" начиная с {item.required_since}"
                if item.required_since
                else " без required_since"
            )
            found.append(
                Operation(
                    FIELD_REQUIRED,
                    element,
                    SAFE if item.required_since else BREAKING,
                    f"поле {item.name} стало обязательным{since}",
                    type_code=code,
                    field=item,
                    previous_field=was,
                )
            )

    for field_id, item in before.items():
        if field_id not in after:
            found.append(
                Operation(
                    FIELD_REMOVED,
                    f"{code}.{field_id}",
                    DESTRUCTIVE,
                    f"удалено поле {item.name}, данные колонки {item.column} будут удалены",
                    type_code=code,
                    field=item,
                )
            )
    return found


def _diff_relations(
    old: Sequence[RelationSignature], new: Sequence[RelationSignature]
) -> list[Operation]:
    found: list[Operation] = []
    old_map, new_map = _by_id(old), _by_id(new)

    for relation_id, entry in new_map.items():
        if relation_id not in old_map:
            found.append(
                Operation(RELATION_ADDED, entry.name, SAFE, "добавлена связь", relation=entry)
            )
            continue
        was = old_map[relation_id]
        if was.name != entry.name:
            found.append(
                Operation(
                    RELATION_RENAMED,
                    str(relation_id),
                    SAFE,
                    f"связь {was.name} -> {entry.name}",
                    relation=entry,
                )
            )
        for side, previous, current in (
            ("from", was.sources, entry.sources),
            ("to", was.targets, entry.targets),
        ):
            removed = tuple(code for code in previous if code not in current)
            added = tuple(code for code in current if code not in previous)
            if added:
                found.append(
                    Operation(
                        f"relation_{side}_widened",
                        entry.name,
                        SAFE,
                        f"{side}: добавлены типы {', '.join(added)}",
                        relation=entry,
                        codes=added,
                    )
                )
            if removed:
                found.append(
                    Operation(
                        f"relation_{side}_narrowed",
                        entry.name,
                        BREAKING,
                        f"{side}: удалены типы {', '.join(removed)}",
                        relation=entry,
                        codes=removed,
                    )
                )
        found += _diff_cardinality(
            entry, "from_cardinality", was.source_cardinality, entry.source_cardinality
        )
        found += _diff_cardinality(
            entry, "to_cardinality", was.target_cardinality, entry.target_cardinality
        )

    for relation_id, entry in old_map.items():
        if relation_id not in new_map:
            found.append(
                Operation(
                    RELATION_REMOVED,
                    entry.name,
                    DESTRUCTIVE,
                    "удалена связь, её рёбра будут удалены",
                    relation=entry,
                )
            )
    return found


def _diff_cardinality(
    relation: RelationSignature, side: str, was: Cardinality, now: Cardinality
) -> list[Operation]:
    if was == now:
        return []
    tightened = now.min > was.min or _narrower_max(was.max, now.max)
    verb = "ужесточена" if tightened else "ослаблена"
    return [
        Operation(
            RELATION_CARDINALITY,
            f"{relation.name}.{side}",
            BREAKING if tightened else SAFE,
            f"{side}: кардинальность {verb} ({_card(was)} -> {_card(now)})",
            relation=relation,
        )
    ]


def _narrower_max(was: int | None, now: int | None) -> bool:
    if now is None:
        return False
    return was is None or now < was


def _card(value: Cardinality) -> str:
    return f"{value.min}..{'*' if value.max is None else value.max}"


# --- гейт совместимости ---------------------------------------------------

#: Исходы решения гейта: выпускать, выпускать нечего, отвергнуто.
RELEASE: Final = "release"
NOTHING_TO_RELEASE: Final = "nothing_to_release"
REJECTED: Final = "rejected"

#: Элемент нарушений гейта, относящихся к версии модели.
_RELEASE_ELEMENT: Final = "выпуск"


@dataclass(frozen=True)
class GateDecision:
    """Решение гейта совместимости по рабочей и последней выпущенной версии.

    Решение — значение, а не исключение: «выпускать нечего» и «отвергнуто» — штатные исходы.
    Отвергнутое решение несёт нарушения, решение «выпускать» — дельту.
    """

    outcome: str
    current: Descriptor
    previous: Descriptor | None
    delta: Delta = Delta()
    findings: tuple[Finding, ...] = ()

    def report(self) -> tuple[str, ...]:
        """Сводка решения для печати: переход версий, операции дельты, предупреждения."""
        if self.outcome == NOTHING_TO_RELEASE:
            return (f"модель не изменялась: {self.current.version}, выпускать нечего",)
        previous = str(self.previous.version) if self.previous else "пусто"
        lines = [f"{previous} -> {self.current.version}"]
        lines += [f"  {item}" for item in self.delta.operations] or ["  начальный выпуск модели"]
        lines += [f"ВНИМАНИЕ  {item.element}: {item.detail}" for item in self.delta.warnings]
        return tuple(lines)


class CompatibilityGate:
    """Гейт совместимости: можно ли выпускать рабочую версию поверх выпущенной.

    Гейт останавливает выпуск только на ошибках процесса (MDL-025): версия понижена, модель
    изменена без повышения версии, номер поля выдан повторно. Сверх нормы гейт отвергает
    повышение версии при неизменной структуре — это расхождение Р1 приёмочного отчёта,
    перенесённое как есть. Ломающие и разрушающие операции выпуск не останавливают: о них
    предупреждает сводка, решение принимает владелец (MDL-024).
    """

    def decide(self, current: Descriptor, previous: Descriptor | None) -> GateDecision:
        if previous is None:
            return GateDecision(RELEASE, current, None)

        same_hash = previous.hash == current.hash
        if current.version < previous.version:
            return self._rejected(
                current,
                previous,
                f"версия понижена: {current.version} ниже выпущенной {previous.version}",
            )
        if same_hash and current.version == previous.version:
            return GateDecision(NOTHING_TO_RELEASE, current, previous)
        if not same_hash and current.version == previous.version:
            return self._rejected(
                current,
                previous,
                f"модель изменена, но версия осталась {current.version}: повысьте средний разряд",
            )
        if same_hash and current.version > previous.version:
            return self._rejected(
                current,
                previous,
                f"версия повышена до {current.version}, но структура модели не изменилась: "
                "выпускать нечего",
            )

        delta = diff(previous, current)
        reused = _reused(previous, delta)
        if reused:
            return GateDecision(REJECTED, current, previous, delta, reused)
        return GateDecision(RELEASE, current, previous, delta)

    def _rejected(self, current: Descriptor, previous: Descriptor, message: str) -> GateDecision:
        return GateDecision(
            REJECTED,
            current,
            previous,
            findings=(Finding(current.place, _RELEASE_ELEMENT, message),),
        )


def _reused(previous: Descriptor, delta: Delta) -> tuple[Finding, ...]:
    """Номера полей, однажды выданные в выпущенной версии и выданные повторно (MDL-016)."""
    occupied = {
        node.code: {item.id for item in node.fields} | set(node.taken.fields)
        for node in previous.types
    }
    found: list[Finding] = []
    for item in delta.operations:
        if item.kind != FIELD_ADDED or item.field is None:
            continue
        number = item.field.id
        if number in occupied.get(item.type_code, set()):
            found.append(
                Finding(
                    item.field.place,
                    f"тип {item.type_code}, поле {number} ({item.field.name})",
                    f"номер поля {number} уже был занят в {item.type_code} "
                    "и не может быть выдан повторно",
                )
            )
    return tuple(found)
