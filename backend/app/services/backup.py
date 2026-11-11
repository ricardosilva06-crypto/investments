"""Consistent SQLite backups using the online backup API (safe while running)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..config import get_settings


def create_backup(keep: int = 14) -> Path:
    settings = get_settings()
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = settings.backup_dir / f"investor-{stamp}.db"
    src = sqlite3.connect(settings.database_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    backups = sorted(settings.backup_dir.glob("investor-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return target


def list_backups() -> list[Path]:
    d = get_settings().backup_dir
    return sorted(d.glob("investor-*.db"), reverse=True) if d.exists() else []
