from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging
from app.services.index_service import IndexService
from app.utils.dates import now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KRX KOSPI 시리즈 일별지수를 기준일 단위로 갱신합니다."
    )
    parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=now_kst().date(),
        help="KRX 기준일(YYYY-MM-DD). 기본값은 실행일 KST입니다.",
    )
    return parser


async def _run(as_of_date: date) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    service = IndexService(settings)
    try:
        summary = await service.refresh(as_of_date)
    finally:
        service.close()
    print(
        json.dumps(
            summary.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if summary.state == "AVAILABLE":
        return 0
    if summary.state in {"NOT_CONFIGURED", "NOT_VERIFIED"}:
        return 2
    return 1


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        return asyncio.run(_run(arguments.as_of))
    except (SQLAlchemyError, OSError, ValidationError) as exc:
        print(
            json.dumps(
                {
                    "state": "FETCH_FAILED",
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
