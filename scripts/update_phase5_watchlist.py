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
from app.services.event_service import EventService

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
        raise argparse.ArgumentTypeError(
            "날짜는 YYYY-MM-DD 형식이어야 합니다."
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "여러 관심종목의 OpenDART·네이버 뉴스·KIS 데이터를 "
            "하나의 KIS 인증 세션으로 수집합니다."
        )
    )
    parser.add_argument(
        "--symbol",
        required=True,
        action="append",
        type=_parse_symbol,
    )
    parser.add_argument("--as-of", required=True, type=_parse_date)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    symbols = list(dict.fromkeys(args.symbol))
    service = EventService(settings)
    summaries = []
    try:
        for symbol in symbols:
            summaries.append(
                await service.refresh(
                    symbol=symbol,
                    as_of_date=args.as_of,
                )
            )
    finally:
        service.close()

    states = [summary.state.value for summary in summaries]
    if all(state == "AVAILABLE" for state in states):
        returncode = 0
        state = "AVAILABLE"
    elif all(state == "NOT_CONFIGURED" for state in states):
        returncode = 2
        state = "NOT_CONFIGURED"
    else:
        returncode = 1
        state = "FETCH_FAILED"
    print(
        json.dumps(
            {
                "state": state,
                "as_of": args.as_of.isoformat(),
                "symbols": symbols,
                "summaries": [
                    summary.model_dump(mode="json")
                    for summary in summaries
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return returncode


def main() -> int:
    args = build_parser().parse_args()
    settings = None
    try:
        settings = get_settings()
        return asyncio.run(_run(args))
    except (OSError, SQLAlchemyError, ValidationError, ValueError) as exc:
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
