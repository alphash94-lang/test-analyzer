from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

DEFAULT_TIMEOUT_SECONDS = 10.0


def send_failure_alert(
    *,
    webhook_url: str | None,
    title: str,
    message: str,
    source: str,
    log_path: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    normalized_url = (webhook_url or "").strip()
    alert_text = f"[{source}] {title}\n{message}"
    if log_path is not None:
        alert_text += f"\n로그: {log_path}"
    if not normalized_url:
        return {
            "state": "NOT_CONFIGURED",
            "detail": "UPDATE_FAILURE_WEBHOOK_URL이 설정되지 않았습니다.",
        }

    owns_client = client is None
    http_client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
    try:
        response = http_client.post(
            normalized_url,
            json={"text": alert_text},
            headers={"content-type": "application/json"},
        )
        response.raise_for_status()
    finally:
        if owns_client:
            http_client.close()
    return {
        "state": "AVAILABLE",
        "http_status": response.status_code,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="자동화 실패를 Slack 호환 Webhook으로 알립니다."
    )
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--source", default="scheduled-update")
    parser.add_argument("--log-path", type=Path)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result = send_failure_alert(
            webhook_url=os.getenv("UPDATE_FAILURE_WEBHOOK_URL"),
            title=arguments.title,
            message=arguments.message,
            source=arguments.source,
            log_path=arguments.log_path,
        )
    except (httpx.HTTPError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "state": "FETCH_FAILED",
                    "error_type": type(exc).__name__,
                    "message": "실패 알림 전송에 실패했습니다.",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
