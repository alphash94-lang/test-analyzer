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
from app.services.price_service import PriceService

_SYMBOL = re.compile(r"^\d{6}$")


def _parse_symbol(value: str) -> str:
    normalized = value.strip()
    if not _SYMBOL.fullmatch(normalized):
        raise argparse.ArgumentTypeError("종목코드는 6자리 숫자여야 합니다.")
    return normalized


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KIS 공식 수정주가 일봉을 수집합니다."
    )
    parser.add_argument("--symbol", required=True, type=_parse_symbol)
    parser.add_argument("--as-of", required=True, type=_parse_date)
    parser.add_argument("--lookback-days", type=int, default=420)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    service = PriceService(settings)
    try:
        summary = await service.refresh_adjusted_history(
            symbol=args.symbol,
            as_of_date=args.as_of,
            lookback_days=args.lookback_days,
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
    return 0 if summary.state == "AVAILABLE" else 1


def main() -> int:
    settings = None
    try:
        settings = get_settings()
        return asyncio.run(_run(build_parser().parse_args()))
    except (OSError, SQLAlchemyError, ValidationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                    "message": safe_exception_message(exc, settings=settings),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
