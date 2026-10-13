"""Чтение модели из каталога YAML: `_manifest.yaml`, `types/*.yaml`, `relations.yaml`.

Адаптер отвечает за формат и только за него: синтаксис YAML, обязательные и неизвестные ключи,
вид значений. Нарушения формата копятся, а не поднимаются: один прогон называет все дефекты
всех файлов, а модель собирается из того, что формат позволил построить (design D4).
Правила структуры — формы кодов и имён, уникальность, занятые номера, ссылки — проверяет
домен, а не разбор: у правила один носитель.

Номер строки берётся из меток узлов `yaml.compose`. У однострочного отображения
`{ id: 1, … }` все ключи на одной строке, поэтому место нарушения поля — строка его записи:
в файлах модели одно поле — одна строка.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..errors import EnvironmentFault
from .domain import (
    ENUM,
    REF,
    SCALAR,
    SCALAR_TYPES,
    Cardinality,
    Enum,
    EnumValue,
    Field,
    Finding,
    Model,
    ModelReading,
    NodeType,
    Place,
    RelationSignature,
    TakenNumbers,
    Version,
    parse_version,
)

MANIFEST = "_manifest.yaml"
TAKEN = "_taken.yaml"
RELATIONS = "relations.yaml"
TYPES = "types"


class YamlModelSource:
    """Реализация `ModelSource` над каталогом модели (MDL-001)."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def read(self) -> ModelReading:
        if not self._root.is_dir():
            raise EnvironmentFault("каталог модели не найден", where=str(self._root))
        return _Reading(self._root).run()


class _Mapping(dict[Any, Any]):
    """Отображение YAML со строками ключей."""

    line: int
    lines: dict[Any, int]


class _Sequence(list[Any]):
    """Последовательность YAML со строками элементов."""

    line: int
    lines: list[int]


_CONSTRUCTOR = yaml.constructor.SafeConstructor()


def _located(node: yaml.Node) -> Any:
    """Значение узла — то же, что дал бы `yaml.safe_load`, — со строками ключей и элементов."""
    if isinstance(node, yaml.MappingNode):
        _CONSTRUCTOR.flatten_mapping(node)
        mapping = _Mapping()
        mapping.line, mapping.lines = node.start_mark.line + 1, {}
        for key_node, value_node in node.value:
            key = _located(key_node)
            mapping[key] = _located(value_node)
            mapping.lines[key] = key_node.start_mark.line + 1
        return mapping
    if isinstance(node, yaml.SequenceNode):
        sequence = _Sequence(_located(item) for item in node.value)
        sequence.line = node.start_mark.line + 1
        sequence.lines = [item.start_mark.line + 1 for item in node.value]
        return sequence
    return _CONSTRUCTOR.construct_object(node, deep=True)


def _line(container: Any, key: Any = None) -> int | None:
    """Строка ключа отображения или элемента последовательности; без ключа — самого узла."""
    if isinstance(container, _Mapping):
        return container.lines.get(key, container.line) if key is not None else container.line
    if isinstance(container, _Sequence):
        if isinstance(key, int) and 0 <= key < len(container.lines):
            return container.lines[key]
        return container.line
    return None


class _Reading:
    """Один прогон чтения каталога модели: файлы по порядку, нарушения формата в накопителе."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._findings: list[Finding] = []

    def run(self) -> ModelReading:
        manifest = self._load(MANIFEST, required=True)
        package, version, enums, place = self._manifest(manifest)
        types = [
            node
            for path in sorted((self._root / TYPES).glob("*.yaml"))
            if (node := self._type(self._load(f"{TYPES}/{path.name}"), f"{TYPES}/{path.name}"))
        ]
        if (self._root / TAKEN).exists():
            types, enums = self._merge_taken(self._load(TAKEN), types, enums)
        relations = (
            self._relations(self._load(RELATIONS)) if (self._root / RELATIONS).exists() else ()
        )

        model = None
        if package is not None and version is not None:
            model = Model(package, version, tuple(enums), tuple(types), relations, place)
        return ModelReading(model, tuple(self._findings))

    # --- вспомогательное --------------------------------------------------

    def _report(self, file: str, line: int | None, element: str, message: str) -> None:
        self._findings.append(Finding(Place(file, line), element, message))

    def _load(self, file: str, *, required: bool = False) -> Any:
        """Разобрать файл; `None` — файла нет, он пуст или не разбирается, нарушение записано."""
        path = self._root / file
        if not path.exists():
            if required:
                self._report(file, None, "файл", "файл не найден")
            return None
        try:
            node = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
            data = None if node is None else _located(node)
        except yaml.MarkedYAMLError as error:
            mark = error.problem_mark or error.context_mark
            line = mark.line + 1 if mark is not None else None
            self._report(file, line, "файл", f"не разбирается как YAML: {error.problem or error}")
            return None
        except (yaml.YAMLError, TypeError) as error:
            self._report(file, None, "файл", f"не разбирается как YAML: {error}")
            return None
        if data is None:
            self._report(file, None, "файл", "файл пуст")
        return data

    def _keys(
        self,
        raw: Any,
        file: str,
        element: str,
        *,
        required: set[str],
        allowed: set[str],
        line: int | None = None,
    ) -> bool:
        """Проверить ключи отображения; `False` — это не отображение или нет обязательных ключей."""
        if not isinstance(raw, dict):
            self._report(file, _line(raw) or line, element, "ожидалось отображение")
            return False
        missing = required - set(raw)
        if missing:
            self._report(
                file,
                _line(raw),
                element,
                f"отсутствуют обязательные ключи: {', '.join(sorted(missing))}",
            )
        unknown = set(raw) - allowed
        if unknown:
            names = ", ".join(sorted(map(str, unknown)))
            self._report(
                file,
                _line(raw, sorted(unknown, key=str)[0]),
                element,
                f"неизвестные ключи: {names}",
            )
        return not missing

    def _int(self, raw: Any, file: str, line: int | None, element: str) -> int | None:
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
            self._report(file, line, element, "ожидалось целое число не меньше единицы")
            return None
        return raw

    def _list(self, raw: Any, file: str, line: int | None, element: str) -> list[Any] | None:
        if not isinstance(raw, list):
            self._report(file, line, element, "ожидался список")
            return None
        return raw

    def _int_list(self, raw: Any, file: str, line: int | None, element: str) -> tuple[int, ...]:
        items = [] if raw is None else self._list(raw, file, line, element) or []
        numbers = [
            self._int(item, file, _line(raw, index) or line, f"{element}[{index}]")
            for index, item in enumerate(items)
        ]
        return tuple(number for number in numbers if number is not None)

    def _str_list(self, raw: Any, file: str, line: int | None, element: str) -> tuple[str, ...]:
        items = [] if raw is None else self._list(raw, file, line, element) or []
        found: list[str] = []
        for index, item in enumerate(items):
            if not isinstance(item, str) or not item:
                self._report(
                    file,
                    _line(raw, index) or line,
                    f"{element}[{index}]",
                    "ожидалась непустая строка",
                )
            else:
                found.append(item)
        return tuple(found)

    def _str(self, raw: Any, file: str, line: int | None, element: str) -> str | None:
        if not isinstance(raw, str):
            self._report(file, line, element, f"значение {raw!r} должно быть строкой")
            return None
        return raw

    def _taken(self, raw: Any, file: str, element: str) -> TakenNumbers:
        if raw is None:
            return TakenNumbers()
        if not isinstance(raw, dict):
            self._report(file, _line(raw), element, "раздел taken должен быть отображением")
            return TakenNumbers()
        unknown = set(raw) - {"fields", "names", "codes"}
        if unknown:
            self._report(
                file,
                _line(raw),
                element,
                f"неизвестные ключи taken: {', '.join(sorted(map(str, unknown)))}",
            )
        return TakenNumbers(
            fields=self._int_list(
                raw.get("fields"), file, _line(raw, "fields"), f"{element}.fields"
            ),
            names=self._str_list(raw.get("names"), file, _line(raw, "names"), f"{element}.names"),
            codes=self._int_list(raw.get("codes"), file, _line(raw, "codes"), f"{element}.codes"),
        )

    # --- манифест и перечисления ------------------------------------------

    def _manifest(self, raw: Any) -> tuple[str | None, Version | None, list[Enum], Place]:
        place = Place(MANIFEST, _line(raw, "version"))
        if raw is None or not self._keys(
            raw,
            MANIFEST,
            "манифест",
            required={"model", "version"},
            allowed={"model", "version", "enums"},
        ):
            return (
                None,
                None,
                self._enums(raw.get("enums") if isinstance(raw, dict) else None, raw),
                place,
            )

        package = raw["model"]
        if not isinstance(package, str) or not package:
            self._report(
                MANIFEST, _line(raw, "model"), "model", "ключ model должен быть непустой строкой"
            )
            package = None
        version = parse_version(raw["version"])
        if version is None:
            message = (
                f"версия {raw['version']!r} не имеет вида 1.2.0"
                if isinstance(raw["version"], str)
                else "версия должна быть строкой вида 1.2.0"
            )
            self._report(MANIFEST, _line(raw, "version"), "version", message)
        return package, version, self._enums(raw.get("enums"), raw), place

    def _enums(self, raw: Any, manifest: Any) -> list[Enum]:
        if raw is None:
            return []
        if not isinstance(raw, dict):
            self._report(
                MANIFEST,
                _line(manifest, "enums"),
                "enums",
                "раздел enums должен быть отображением имя -> описание",
            )
            return []
        found: list[Enum] = []
        for name, body in raw.items():
            element = f"enums.{name}"
            line = _line(raw, name)
            if not isinstance(body, dict):
                self._report(
                    MANIFEST, line, element, "описание перечисления должно быть отображением"
                )
                continue
            if not self._keys(
                body,
                MANIFEST,
                element,
                required={"id", "values"},
                allowed={"id", "values", "taken"},
            ):
                continue
            number = self._int(body["id"], MANIFEST, _line(body, "id"), f"{element}.id")
            values = self._values(body["values"], _line(body, "values"), element)
            taken = self._taken(body.get("taken"), MANIFEST, f"{element}.taken")
            if number is not None:
                found.append(Enum(number, str(name), values, taken, Place(MANIFEST, line)))
        return found

    def _values(self, raw: Any, line: int | None, element: str) -> tuple[EnumValue, ...]:
        items = self._list(raw, MANIFEST, line, f"{element}.values") or []
        found: list[EnumValue] = []
        for index, item in enumerate(items):
            where = f"{element}.values[{index}]"
            item_line = _line(raw, index) or line
            if not isinstance(item, dict):
                self._report(MANIFEST, item_line, where, "элемент списка должен быть отображением")
                continue
            number = self._int(item.get("id"), MANIFEST, _line(item, "id"), f"{where}.id")
            name = self._str(item.get("name"), MANIFEST, _line(item, "name"), f"{where}.name")
            if number is not None and name is not None:
                found.append(EnumValue(number, name, Place(MANIFEST, item_line)))
        return tuple(found)

    # --- типы узлов -------------------------------------------------------

    def _type(self, raw: Any, file: str) -> NodeType | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            self._report(file, _line(raw), "тип", "описание типа должно быть отображением")
            return None
        complete = self._keys(
            raw,
            file,
            "тип",
            required={"type", "id", "name", "fields"},
            allowed={"type", "id", "name", "fields", "taken", "description"},
        )
        code = (
            self._str(raw.get("type"), file, _line(raw, "type"), "type") if "type" in raw else None
        )
        number = self._int(raw["id"], file, _line(raw, "id"), "id") if "id" in raw else None
        names = raw.get("name")
        if "name" in raw and (
            not isinstance(names, dict) or "ru" not in names or "en" not in names
        ):
            self._report(file, _line(raw, "name"), "name", "name должен содержать ключи ru и en")
            names = None
        fields = self._fields(raw["fields"], file, _line(raw, "fields")) if "fields" in raw else ()
        taken = self._taken(raw.get("taken"), file, "taken")
        if not complete or code is None or number is None or names is None:
            return None
        return NodeType(
            id=number,
            code=code,
            name_ru=str(names["ru"]),
            name_en=str(names["en"]),
            fields=fields,
            taken=taken,
            description=raw.get("description"),
            place=Place(file, _line(raw, "type")),
        )

    def _fields(self, raw: Any, file: str, line: int | None) -> tuple[Field, ...]:
        items = self._list(raw, file, line, "fields") or []
        found: list[Field] = []
        for index, item in enumerate(items):
            where = f"fields[{index}]"
            item_line = _line(raw, index) or line
            if not isinstance(item, dict):
                self._report(file, item_line, where, "элемент списка должен быть отображением")
                continue
            parsed = self._field(item, file, item_line, where)
            if parsed is not None:
                found.append(parsed)
        return tuple(found)

    def _field(self, raw: dict[str, Any], file: str, line: int | None, where: str) -> Field | None:
        valid = self._keys(
            raw,
            file,
            where,
            required={"id", "name", "type"},
            allowed={"id", "name", "type", "required", "required_since", "description"},
        )
        required = raw.get("required", False)
        if not isinstance(required, bool):
            self._report(
                file,
                _line(raw, "required"),
                f"{where}.required",
                "required должен быть true или false",
            )
            valid = False
        since = raw.get("required_since")
        if since is not None and (not isinstance(since, int) or since < 0):
            self._report(
                file,
                _line(raw, "required_since"),
                f"{where}.required_since",
                "required_since должен быть средним разрядом версии",
            )
            valid = False
        elif since is not None and required is False:
            self._report(file, line, where, "required_since указан у необязательного поля")
        number = (
            self._int(raw.get("id"), file, _line(raw, "id"), f"{where}.id") if "id" in raw else None
        )
        name = (
            self._str(raw.get("name"), file, _line(raw, "name"), f"{where}.name")
            if "name" in raw
            else None
        )
        kind = (
            self._field_type(raw.get("type"), file, _line(raw, "type"), f"{where}.type")
            if "type" in raw
            else None
        )
        if not valid or number is None or name is None or kind is None:
            return None
        return Field(
            id=number,
            name=name,
            kind=kind[0],
            type=kind[1],
            required=bool(required),
            required_since=since,
            description=raw.get("description"),
            place=Place(file, line),
        )

    def _field_type(
        self, raw: Any, file: str, line: int | None, where: str
    ) -> tuple[str, str] | None:
        """Вид и имя типа поля из записи `text`, `enum.<имя>`, `ref.<ТИП>` (MDL-011)."""
        if not isinstance(raw, str) or not raw:
            self._report(file, line, where, "тип поля должен быть непустой строкой")
            return None
        if raw in SCALAR_TYPES:
            return SCALAR, raw
        for prefix, kind in (("enum.", ENUM), ("ref.", REF)):
            if raw.startswith(prefix):
                target = raw[len(prefix) :]
                if not target:
                    self._report(file, line, where, f"после {prefix!r} не указано имя")
                    return None
                return kind, target
        self._report(
            file,
            line,
            where,
            f"неизвестный тип {raw!r}: ожидается один из {', '.join(SCALAR_TYPES)}"
            " либо enum.<имя> / ref.<ТИП>",
        )
        return None

    # --- занятые номера инструмента ---------------------------------------

    def _merge_taken(
        self, raw: Any, types: list[NodeType], enums: list[Enum]
    ) -> tuple[list[NodeType], list[Enum]]:
        """Соединить занятые номера из файлов элементов и из файла, который ведёт инструмент."""
        if raw is None or not self._keys(
            raw, TAKEN, "занятые номера", required=set(), allowed={"types", "enums"}
        ):
            return types, enums
        by_type = raw.get("types") or {}
        by_enum = raw.get("enums") or {}
        if not isinstance(by_type, dict) or not isinstance(by_enum, dict):
            self._report(
                TAKEN,
                _line(raw),
                "занятые номера",
                "разделы types и enums должны быть отображениями",
            )
            return types, enums
        return (
            [self._merged(node, by_type.get(node.code), f"types.{node.code}") for node in types],
            [
                self._merged(enum_, by_enum.get(enum_.name), f"enums.{enum_.name}")
                for enum_ in enums
            ],
        )

    def _merged[Element: (NodeType, Enum)](
        self, element: Element, extra: Any, where: str
    ) -> Element:
        if extra is None:
            return element
        added = self._taken(extra, TAKEN, where)
        return replace(
            element,
            taken=TakenNumbers(
                fields=tuple(sorted(set(element.taken.fields) | set(added.fields))),
                names=tuple(sorted(set(element.taken.names) | set(added.names))),
                codes=tuple(sorted(set(element.taken.codes) | set(added.codes))),
            ),
        )

    # --- сигнатуры связей -------------------------------------------------

    def _relations(self, raw: Any) -> tuple[RelationSignature, ...]:
        if raw is None or not self._keys(
            raw, RELATIONS, "relations", required={"relations"}, allowed={"relations"}
        ):
            return ()
        items = self._list(raw["relations"], RELATIONS, _line(raw, "relations"), "relations") or []
        found = [
            relation
            for index, item in enumerate(items)
            if (
                relation := self._relation(
                    item, _line(raw["relations"], index), f"relations[{index}]"
                )
            )
        ]
        return tuple(found)

    def _relation(self, raw: Any, line: int | None, where: str) -> RelationSignature | None:
        if not isinstance(raw, dict):
            self._report(RELATIONS, line, where, "описание связи должно быть отображением")
            return None
        complete = self._keys(
            raw,
            RELATIONS,
            where,
            required={"id", "name", "from", "to"},
            allowed={
                "id",
                "name",
                "from",
                "to",
                "from_cardinality",
                "to_cardinality",
                "acyclic",
                "description",
            },
        )
        sources = self._side(raw, "from", where, "не указан домен связи (from)")
        targets = self._side(raw, "to", where, "не указан кодомен связи (to)")
        acyclic = raw.get("acyclic", True)
        if not isinstance(acyclic, bool):
            self._report(
                RELATIONS,
                _line(raw, "acyclic"),
                f"{where}.acyclic",
                "acyclic должен быть true или false",
            )
        number = (
            self._int(raw["id"], RELATIONS, _line(raw, "id"), f"{where}.id")
            if "id" in raw
            else None
        )
        name = (
            self._str(raw["name"], RELATIONS, _line(raw, "name"), f"{where}.name")
            if "name" in raw
            else None
        )
        source_cardinality = self._cardinality(raw, "from_cardinality", where)
        target_cardinality = self._cardinality(raw, "to_cardinality", where)
        if (
            not complete
            or number is None
            or name is None
            or not sources
            or not targets
            or not isinstance(acyclic, bool)
            or source_cardinality is None
            or target_cardinality is None
        ):
            return None
        return RelationSignature(
            id=number,
            name=name,
            sources=sources,
            targets=targets,
            source_cardinality=source_cardinality,
            target_cardinality=target_cardinality,
            acyclic=acyclic,
            description=raw.get("description"),
            place=Place(RELATIONS, line),
        )

    def _side(self, relation: dict[str, Any], key: str, where: str, empty: str) -> tuple[str, ...]:
        """Домен или кодомен связи: непустой перечень кодов типов (MDL-013)."""
        if key not in relation:
            return ()
        raw = relation[key]
        if raw is None or raw == []:
            self._report(RELATIONS, _line(relation, key), where, empty)
            return ()
        return self._str_list(raw, RELATIONS, _line(relation, key), f"{where}.{key}")

    def _cardinality(self, relation: dict[str, Any], key: str, where: str) -> Cardinality | None:
        raw, line, element = relation.get(key), _line(relation, key), f"{where}.{key}"
        if raw is None:
            return Cardinality()
        if not isinstance(raw, dict):
            self._report(
                RELATIONS, line, element, "кардинальность должна быть отображением min/max"
            )
            return None
        unknown = set(raw) - {"min", "max"}
        if unknown:
            self._report(
                RELATIONS,
                line,
                element,
                f"неизвестные ключи: {', '.join(sorted(map(str, unknown)))}",
            )
            return None
        low = raw.get("min", 0)
        high = raw.get("max", None)
        if not isinstance(low, int) or low < 0:
            self._report(RELATIONS, line, element, "min должен быть целым не меньше нуля")
            return None
        if high is not None and (not isinstance(high, int) or high < 1):
            self._report(
                RELATIONS,
                line,
                element,
                "max должен быть целым не меньше единицы либо отсутствовать",
            )
            return None
        if high is not None and high < low:
            self._report(RELATIONS, line, element, "max меньше min")
            return None
        return Cardinality(low, high)
