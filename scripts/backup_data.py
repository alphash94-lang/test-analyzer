from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings
from app.utils.dates import now_kst

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
_SAFE_LABEL = re.compile(r"[^a-zA-Z0-9_-]+")


def _resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(
            "자동 DB 백업은 현재 SQLite만 지원합니다. "
            "PostgreSQL은 pg_dump 운영 절차를 사용해 주세요."
        )
    if not url.database or url.database == ":memory:":
        raise ValueError("파일 기반 SQLite DATABASE_URL이 필요합니다.")
    return _resolve_project_path(Path(url.database)).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_sqlite(source_path: Path, destination_path: Path) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite DB를 찾을 수 없습니다: {source_path}")
    with (
        sqlite3.connect(source_path) as source,
        sqlite3.connect(destination_path) as destination,
    ):
        source.backup(destination)


def _archive_raw_responses(raw_dir: Path, destination_path: Path) -> int:
    file_count = 0
    with zipfile.ZipFile(
        destination_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        if raw_dir.is_dir():
            for path in sorted(raw_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(raw_dir))
                    file_count += 1
    return file_count


def _prune_old_backups(
    backup_root: Path,
    *,
    cutoff: datetime,
    protected: Path,
) -> int:
    removed = 0
    for candidate in backup_root.iterdir():
        if (
            candidate == protected
            or not candidate.is_dir()
            or candidate.name.startswith(".tmp-")
        ):
            continue
        modified_at = datetime.fromtimestamp(
            candidate.stat().st_mtime,
            tz=cutoff.tzinfo,
        )
        if modified_at < cutoff:
            shutil.rmtree(candidate)
            removed += 1
    return removed


def create_backup(
    *,
    database_url: str,
    raw_data_dir: Path,
    backup_root: Path = DEFAULT_BACKUP_DIR,
    retention_days: int = 30,
    label: str = "scheduled",
    created_at: datetime | None = None,
) -> dict[str, object]:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    timestamp = created_at or now_kst()
    safe_label = _SAFE_LABEL.sub("-", label.strip()).strip("-") or "backup"
    backup_root = _resolve_project_path(backup_root).resolve()
    raw_data_dir = _resolve_project_path(raw_data_dir).resolve()
    database_path = _sqlite_database_path(database_url)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_name = f"{timestamp:%Y%m%d_%H%M%S}_{safe_label}"
    final_dir = backup_root / backup_name
    if final_dir.exists():
        raise FileExistsError(f"백업 경로가 이미 존재합니다: {final_dir}")

    final_dir.mkdir()
    incomplete_marker = final_dir / ".incomplete"
    incomplete_marker.write_text(
        timestamp.isoformat(),
        encoding="utf-8",
    )
    try:
        database_backup = final_dir / "database.sqlite3"
        raw_archive = final_dir / "raw_responses.zip"
        _backup_sqlite(database_path, database_backup)
        raw_file_count = _archive_raw_responses(raw_data_dir, raw_archive)
        manifest = {
            "created_at": timestamp.isoformat(),
            "label": safe_label,
            "database": {
                "filename": database_backup.name,
                "sha256": _sha256(database_backup),
                "bytes": database_backup.stat().st_size,
            },
            "raw_responses": {
                "filename": raw_archive.name,
                "sha256": _sha256(raw_archive),
                "bytes": raw_archive.stat().st_size,
                "files": raw_file_count,
            },
        }
        (final_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        incomplete_marker.unlink()
    except BaseException:
        shutil.rmtree(final_dir, ignore_errors=True)
        raise

    removed = _prune_old_backups(
        backup_root,
        cutoff=timestamp - timedelta(days=retention_days),
        protected=final_dir,
    )
    return {
        "state": "AVAILABLE",
        "backup_path": str(final_dir),
        "created_at": timestamp.isoformat(),
        "retention_days": retention_days,
        "old_backups_removed": removed,
        **manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SQLite DB와 API 원응답을 검증 가능한 형태로 백업합니다."
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
    )
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--label", default="scheduled")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    settings = get_settings()
    try:
        summary = create_backup(
            database_url=settings.database_url,
            raw_data_dir=settings.raw_data_dir,
            backup_root=arguments.backup_dir,
            retention_days=arguments.retention_days,
            label=arguments.label,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(
            json.dumps(
                {
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
