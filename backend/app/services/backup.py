"""Full backups: a consistent SQLite snapshot plus uploaded PDFs, in one zip.

The database is copied with SQLite's online backup API (safe while running).
Backups contain every member's private data: keep them somewhere safe, ideally
encrypted (e.g. an encrypted disk or `age`/`7z` with a password).
"""

import json
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ..config import get_settings

PATTERNS = ("investor-*.zip", "investor-*.db")


def create_backup(keep: int | None = None) -> Path:
    settings = get_settings()
    keep = settings.backups_keep if keep is None else keep
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = settings.backup_dir / f"investor-{stamp}.zip"
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp:
        snap = Path(tmp) / "investor.db"
        src = sqlite3.connect(settings.database_path)
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        docs = sorted(p for p in settings.documents_dir.rglob("*") if p.is_file()) if settings.documents_dir.exists() else []
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "format": "investor-intelligence-backup/2",
            "database": "investor.db",
            "documents": len(docs),
            "restore": "Stop the server, then replace data/investor.db and data/documents/ with the files in this archive.",
        }
        partial = target.with_suffix(".zip.part")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "investor.db")
            for p in docs:
                z.write(p, f"documents/{p.relative_to(settings.documents_dir).as_posix()}")
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
        partial.rename(target)
    backups = list_backups()
    for old in backups[keep:] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return target


def list_backups() -> list[Path]:
    d = get_settings().backup_dir
    if not d.exists():
        return []
    files = [p for pat in PATTERNS for p in d.glob(pat)]
    return sorted(files, key=lambda p: p.name, reverse=True)
