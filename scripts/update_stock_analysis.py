from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging, safe_exception_message
from app.services.stock_analysis_service import StockAnalysisService

_SYMBOL = re.compile(r"^\d{6}$")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "날짜는 YYYY-MM-DD 형식이어야 합니다."
        ) from exc


def _parse_symbol(value: str) -> str:
    normalized = value.strip()
    if not _SYMBOL.fullmatch(normalized):
        raise argparse.ArgumentTypeError("종목코드는 6자리 숫자여야 합니다.")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("OpenDART 재무·배당·감사의견을 한 종목 단위로 증분 수집합니다.")
    )
    parser.add_argument("--symbol", required=True, type=_parse_symbol)
    parser.add_argument("--as-of", required=True, type=_parse_date)
    parser.add_argument("--years", type=int, choices=range(1, 6), default=5)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    service = StockAnalysisService(settings)
    try:
        summary = await service.refresh(
            symbol=args.symbol,
            as_of_date=args.as_of,
            years=args.years,
        )
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
    if summary.state == "NOT_CONFIGURED":
        return 2
    if summary.state == "MISSING":
        return 3
    return 1


def main() -> int:
    args = build_parser().parse_args()
    settings = None
    try:
        settings = get_settings()
        return asyncio.run(_run(args))
    except (
        OSError,
        SQLAlchemyError,
        ValidationError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                    "message": safe_exception_message(
                        exc,
                        settings=settings,
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
