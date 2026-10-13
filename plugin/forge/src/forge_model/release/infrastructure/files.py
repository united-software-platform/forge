"""Файлы выпуска: каталог миграций, выпущенные дескрипторы, реестр выпусков, занятые номера.

Запись и чтение — разные компоненты (CQRS-006): `FileReleaseRepository` пишет агрегат выпуска,
`FileReleasedDescriptors`, `FileRegistryEntries` и `FileMigrationNames` читают. Адрес каждого
файла складывает один компонент `ChangelogPaths`, поэтому запись и чтение не расходятся в том,
где лежит файл (отклонение эталона D03 не повторено).

Файл дескриптора пишется и читается в канонической форме домена контракта модели: байты файла
совпадают с тем, по чему считается хеш. Реестр — производный указатель, а не источник истины:
цепочка версий восстанавливается из самих миграций по хешам, реестр лишь быстро отвечает,
что выпущено, и хранит контрольные суммы для сверки неизменяемости (MDL-036).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from ...contract.domain import (
    Cardinality,
    Descriptor,
    Enum,
    EnumValue,
    Field,
    NodeType,
    RelationSignature,
    TakenNumbers,
    Version,
    descriptor_document,
    parse_version,
)
from ...errors import EnvironmentFault
from ..domain import RELEASE_EXISTS, RELEASE_WRITTEN, RegistryEntry, Release, checksum

MASTER: Final = "master.yaml"
REGISTRY: Final = "registry.yaml"
TAKEN: Final = "_taken.yaml"

MASTER_HEADER: Final = (
    "# Порядок применения миграций. Файл генерируется, править вручную не нужно.\n"
)
REGISTRY_HEADER: Final = "# Реестр выпусков. Файл генерируется, править вручную не нужно.\n"
TAKEN_HEADER: Final = (
    "# Занятые навсегда номера и имена. Файл ведёт инструмент, править вручную не нужно.\n"
)


@dataclass(frozen=True)
class ChangelogPaths:
    """Адреса файлов выпуска: каталог модели, каталог выпущенных дескрипторов, каталог миграций."""

    model: Path
    releases: Path
    changelog: Path

    def migration(self, address: str) -> Path:
        """Файл миграции по адресу от корня каталога миграций."""
        return self.changelog / address

    def folder(self, folder: str) -> Path:
        return self.changelog / folder

    def descriptor(self, version: str) -> Path:
        """Дескриптор выпущенной версии (MDL-003)."""
        return self.releases / f"{version}.json"

    @property
    def master(self) -> Path:
        return self.changelog / MASTER

    @property
    def registry(self) -> Path:
        return self.changelog / REGISTRY

    @property
    def taken(self) -> Path:
        """Файл занятых номеров, который ведёт инструмент, — в каталоге модели."""
        return self.model / TAKEN


def descriptor_text(descriptor: Descriptor) -> str:
    """Текст файла дескриптора: читаемый отступ, стабильный порядок, перевод строки в конце."""
    document = descriptor_document(descriptor)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


class FileReleaseRepository:
    """Реализация `ReleaseRepository`: пишет агрегат выпуска целиком.

    Порядок записи: миграции, порядок применения, занятые номера, дескриптор версии, запись
    реестра. Выпущенное не перезаписывается (MDL-035): если хотя бы один адрес миграции занят,
    выпуск не пишется вовсе.
    """

    def __init__(self, paths: ChangelogPaths) -> None:
        self._paths = paths

    def add(self, release: Release) -> Literal["written", "exists"]:
        targets = [self._paths.migration(migration.address) for migration in release.migrations]
        if any(target.exists() for target in targets):
            return RELEASE_EXISTS
        self._paths.changelog.mkdir(parents=True, exist_ok=True)
        for migration, target in zip(release.migrations, targets, strict=True):
            target.parent.mkdir(parents=True, exist_ok=True)
            # Без перевода строк: контрольная сумма реестра считается по тексту миграции.
            target.write_text(migration.text, encoding="utf-8", newline="\n")
        self._append_master(release.order)
        self._record_taken(release.taken)
        self._paths.releases.mkdir(parents=True, exist_ok=True)
        self._paths.descriptor(str(release.version)).write_text(
            descriptor_text(release.descriptor), encoding="utf-8"
        )
        self._append_registry(release.registry_entry)
        return RELEASE_WRITTEN

    def _append_master(self, order: Iterable[str]) -> None:
        """Дописать порядок применения: master перечисляет включения явно (MDL-032)."""
        path = self._paths.master
        existing: list[dict[str, Any]] = []
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            existing = data.get("databaseChangeLog", [])
        entries = existing + [
            {"include": {"file": address, "relativeToChangelogFile": True}} for address in order
        ]
        path.write_text(
            MASTER_HEADER
            + yaml.safe_dump({"databaseChangeLog": entries}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _record_taken(self, taken: Iterable[tuple[str, Field]]) -> None:
        """Дописать номера и имена удалённых полей в файл, который ведёт инструмент (MDL-017)."""
        taken = list(taken)
        if not taken:
            return
        path = self._paths.taken
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}) or {}
        types = data.setdefault("types", {})
        for code, field in taken:
            entry = types.setdefault(code, {})
            entry["fields"] = sorted(set(entry.get("fields", [])) | {field.id})
            entry["names"] = sorted(set(entry.get("names", [])) | {field.name})
        path.write_text(
            TAKEN_HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def _append_registry(self, entry: RegistryEntry) -> None:
        """Записать выпуск версии: её хеш и контрольные суммы выпущенных файлов."""
        entries = _registry(self._paths)
        entries.append(
            {
                "version": entry.version,
                "hash": entry.hash,
                "files": [{"path": address, "checksum": value} for address, value in entry.files],
            }
        )
        self._paths.registry.write_text(
            REGISTRY_HEADER + yaml.safe_dump(entries, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


class FileReleasedDescriptors:
    """Реализация `ReleasedDescriptors` над каталогом выпущенных дескрипторов."""

    def __init__(self, paths: ChangelogPaths) -> None:
        self._paths = paths

    def latest(self, major: int) -> Descriptor | None:
        """Последний выпущенный дескриптор того же старшего разряда."""
        if not self._paths.releases.is_dir():
            return None
        best: tuple[Version, Mapping[str, Any]] | None = None
        for path in sorted(self._paths.releases.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            version = parse_version(data.get("version"))
            if version is None:
                raise EnvironmentFault(
                    f"версия {data.get('version')!r} не имеет вида 1.2.0", where=str(path)
                )
            if version.major == major and (best is None or version > best[0]):
                best = (version, data)
        return None if best is None else descriptor_from_document(best[1], best[0])


@dataclass(frozen=True)
class ReleasedFileState:
    """Выпущенный файл: адрес, версия выпуска, записанная и фактическая контрольные суммы.

    Фактической суммы нет, если файл удалён. Сравнивает суммы домен хранилища, а не адаптер.
    """

    address: str
    version: str
    recorded: str
    actual: str | None


class FileRegistryEntries:
    """Чтение реестра выпусков: выпущенные файлы с пересчитанными контрольными суммами."""

    def __init__(self, paths: ChangelogPaths) -> None:
        self._paths = paths

    def files(self) -> tuple[ReleasedFileState, ...]:
        found: list[ReleasedFileState] = []
        for entry in _registry(self._paths):
            for item in entry["files"]:
                path = self._paths.migration(item["path"])
                actual = checksum(path.read_bytes()) if path.exists() else None
                found.append(
                    ReleasedFileState(item["path"], str(entry["version"]), item["checksum"], actual)
                )
        return tuple(found)


class FileMigrationNames:
    """Реализация `MigrationNames`: имена файлов, уже лежащих в каталоге миграций."""

    def __init__(self, paths: ChangelogPaths) -> None:
        self._paths = paths

    def taken(self, folder: str) -> frozenset[str]:
        return frozenset(path.name for path in self._paths.folder(folder).glob("*"))


def _registry(paths: ChangelogPaths) -> list[dict[str, Any]]:
    if not paths.registry.exists():
        return []
    entries: list[dict[str, Any]] = yaml.safe_load(paths.registry.read_text(encoding="utf-8")) or []
    return entries


def descriptor_from_document(data: Mapping[str, Any], version: Version) -> Descriptor:
    """Дескриптор выпущенной версии из его канонической формы."""
    return Descriptor(
        model=data.get("model", ""),
        version=version,
        enums=tuple(
            Enum(
                id=entry["id"],
                name=entry["name"],
                values=tuple(EnumValue(value["id"], value["name"]) for value in entry["values"]),
                taken=_taken(entry.get("taken")),
            )
            for entry in data.get("enums", [])
        ),
        types=tuple(
            NodeType(
                id=entry["id"],
                code=entry["code"],
                name_ru=entry.get("name_ru", ""),
                name_en=entry.get("name_en", ""),
                fields=tuple(
                    Field(
                        id=item["id"],
                        name=item["name"],
                        kind=item["kind"],
                        type=item["type"],
                        required=item["required"],
                        required_since=item["required_since"],
                        description=item.get("description"),
                    )
                    for item in entry["fields"]
                ),
                taken=_taken(entry.get("taken")),
                description=entry.get("description"),
            )
            for entry in data.get("types", [])
        ),
        relations=tuple(
            RelationSignature(
                id=entry["id"],
                name=entry["name"],
                sources=tuple(entry["from"]),
                targets=tuple(entry["to"]),
                source_cardinality=Cardinality(**entry["from_cardinality"]),
                target_cardinality=Cardinality(**entry["to_cardinality"]),
                acyclic=entry["acyclic"],
                description=entry.get("description"),
            )
            for entry in data.get("relations", [])
        ),
        hash=data["hash"],
    )


def _taken(raw: Mapping[str, Any] | None) -> TakenNumbers:
    raw = raw or {}
    return TakenNumbers(
        fields=tuple(raw.get("fields", [])),
        names=tuple(raw.get("names", [])),
        codes=tuple(raw.get("codes", [])),
    )
