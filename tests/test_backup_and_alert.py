from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from scripts.backup_data import create_backup
from scripts.send_failure_alert import send_failure_alert

SEOUL = ZoneInfo("Asia/Seoul")


def test_backup_copies_sqlite_and_archives_raw_responses(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "source.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('verified')")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "response.json").write_text('{"ok":true}', encoding="utf-8")

    result = create_backup(
        database_url=f"sqlite:///{database_path.as_posix()}",
        raw_data_dir=raw_dir,
        backup_root=tmp_path / "backups",
        created_at=datetime(2026, 7, 30, 18, 30, tzinfo=SEOUL),
        label="pre-update",
    )

    backup_path = Path(str(result["backup_path"]))
    manifest = json.loads(
        (backup_path / "manifest.json").read_text(encoding="utf-8")
    )
    with sqlite3.connect(backup_path / "database.sqlite3") as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == (
            "verified",
        )
    with zipfile.ZipFile(backup_path / "raw_responses.zip") as archive:
        assert archive.namelist() == ["response.json"]
        assert archive.read("response.json") == b'{"ok":true}'
    assert manifest["database"]["sha256"]
    assert manifest["raw_responses"]["files"] == 1


def test_backup_prunes_expired_directories(tmp_path: Path) -> None:
    database_path = tmp_path / "source.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sample (value INTEGER)")
    backup_root = tmp_path / "backups"
    expired = backup_root / "20260101_000000_old"
    expired.mkdir(parents=True)
    old_timestamp = datetime(2026, 1, 1, tzinfo=SEOUL).timestamp()
    import os

    os.utime(expired, (old_timestamp, old_timestamp))

    result = create_backup(
        database_url=f"sqlite:///{database_path.as_posix()}",
        raw_data_dir=tmp_path / "missing-raw",
        backup_root=backup_root,
        retention_days=30,
        created_at=datetime(2026, 7, 30, 18, 30, tzinfo=SEOUL),
    )

    assert result["old_backups_removed"] == 1
    assert not expired.exists()


def test_failure_alert_is_optional_without_webhook() -> None:
    result = send_failure_alert(
        webhook_url=None,
        title="수집 실패",
        message="단계 오류",
        source="test",
    )

    assert result["state"] == "NOT_CONFIGURED"


def test_failure_alert_posts_slack_compatible_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = send_failure_alert(
            webhook_url="https://hooks.example.test/services/test",
            title="CI failed",
            message="commit abc",
            source="github-actions",
            log_path=Path("run.log"),
            client=client,
        )

    assert result == {"state": "AVAILABLE", "http_status": 200}
    payload = json.loads(requests[0].content)
    assert payload["text"] == (
        "[github-actions] CI failed\ncommit abc\n로그: run.log"
    )
