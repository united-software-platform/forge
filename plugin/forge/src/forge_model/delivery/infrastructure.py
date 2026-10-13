"""Файлы поставки под корнем плагина: чтение и вырезание раздела нормы.

Корень поставки вычисляется от расположения пакета, а не от рабочего каталога: так файлы
находит и вход из кеша установки, и разработка в репозитории-источнике. В проект-потребитель
файлы не копируются — выдаются текстом.

Раздел нормы вырезается по заголовкам Markdown: это знание формата файла норм, поэтому оно
живёт здесь, а не в сценарии (design D9).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from ..errors import EnvironmentFault

PLUGIN_ROOT: Final = Path(__file__).resolve().parents[3]
RULES: Final = Path("share/rules/model-rules.md")
GLOSSARY: Final = Path("share/docs/glossary.md")
SAMPLE: Final = Path("templates/sample-model")

_HEADING = re.compile(r"^(#{1,6})\s")


class PackageDeliveryFiles:
    """Реализация `DeliveryFiles` над файлами корня поставки."""

    def __init__(self, root: Path = PLUGIN_ROOT) -> None:
        self._root = root

    def rules(self) -> str:
        return self._read(RULES)

    def glossary(self) -> str:
        return self._read(GLOSSARY)

    def rule(self, code: str) -> str:
        """Раздел нормы: от заголовка, под которым стоит абзац `**[КОД]**`, до следующего
        заголовка того же или более высокого уровня."""
        lines = self._read(RULES).splitlines()
        marker = f"**[{code}]**"
        heading: tuple[int, int] | None = None

        for index, line in enumerate(lines):
            match = _HEADING.match(line)
            if match:
                heading = (index, len(match.group(1)))
            elif line.startswith(marker) and heading is not None:
                start, level = heading
                end = next(
                    (
                        after
                        for after in range(index + 1, len(lines))
                        if (found := _HEADING.match(lines[after])) and len(found.group(1)) <= level
                    ),
                    len(lines),
                )
                return "\n".join(lines[start:end]).rstrip() + "\n"

        raise EnvironmentFault(f"правило {code} не найдено", where="нормы модели")

    def sample(self) -> tuple[tuple[str, str], ...]:
        root = self._root / SAMPLE
        # Порядок — сортировка путей, а не строк: так же, как до раскладки по слоям.
        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            raise EnvironmentFault("образец модели не найден", where=str(root))
        return tuple(
            (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")) for path in files
        )

    def _read(self, relative: Path) -> str:
        path = self._root / relative
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise EnvironmentFault("файл поставки не найден", where=str(path)) from error
