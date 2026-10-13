"""Данные поставки плагина: нормы модели, глоссарий, образец модели.

Файлы лежат под корнем плагина, рядом с ядром: корень вычисляется от расположения пакета,
а не от рабочего каталога, — так их находит и вход из кеша установки, и разработка
в репозитории-источнике. В проект-потребитель они не копируются: выдаются текстом.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import EnvironmentFault

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
RULES = Path("share/rules/model-rules.md")
GLOSSARY = Path("share/docs/glossary.md")
SAMPLE = Path("templates/sample-model")

#: Разделитель файлов в выводе образца: путь файла относительно корня проекта.
SAMPLE_SEPARATOR = "==> {path} <=="

_HEADING = re.compile(r"^(#{1,6})\s")


def _read(relative: Path) -> str:
    path = PLUGIN_ROOT / relative
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise EnvironmentFault("файл поставки не найден", where=str(path)) from error


def norms() -> str:
    """Все нормы модели и глоссарий их понятий."""
    return f"{_read(RULES).rstrip()}\n\n{_read(GLOSSARY).rstrip()}\n"


def rule(code: str) -> str:
    """Раздел нормы: от заголовка, под которым стоит абзац `**[КОД]**`, до следующего
    заголовка того же или более высокого уровня."""
    lines = _read(RULES).splitlines()
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


def sample() -> str:
    """Образец минимальной модели: файлы с разделителями-путями."""
    root = PLUGIN_ROOT / SAMPLE
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise EnvironmentFault("образец модели не найден", where=str(root))
    chunks = [
        f"{SAMPLE_SEPARATOR.format(path=path.relative_to(root).as_posix())}\n"
        f"{path.read_text(encoding='utf-8').rstrip()}\n"
        for path in files
    ]
    return "\n".join(chunks)
