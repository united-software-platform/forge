"""Системные часы выпуска: метка времени входит в имена файлов миграций (MDL-031)."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Реализация `Clock`: текущее время UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
