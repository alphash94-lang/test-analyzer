from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging, safe_exception_message
from app.services.phase2_service import Phase2ScoringService
from app.utils.dates import SEOUL

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


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("예정 주문금액은 숫자여야 합니다.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise argparse.ArgumentTypeError(
            "예정 주문금액은 0 이상의 유한한 숫자여야 합니다."
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "저장된 공식 데이터를 사용해 한 종목의 Phase 2 강제필터와 "
            "설명 가능한 점수를 계산합니다."
        )
    )
    parser.add_argument("--symbol", required=True, type=_parse_symbol)
    parser.add_argument("--as-of", required=True, type=_parse_date)
    parser.add_argument(
        "--planned-order-amount",
        type=_parse_decimal,
        default=None,
        help="KRW 단위 예정 주문금액. 미지정 시 설정값을 사용합니다.",
    )
    return parser


def _as_of_at(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), tzinfo=SEOUL)


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    service = Phase2ScoringService(settings)
    try:
        result = service.evaluate(
            args.symbol,
            as_of_at=_as_of_at(args.as_of),
            planned_order_amount=args.planned_order_amount,
        )
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
    finally:
        service.close()
    if result is None:
        print(
            json.dumps(
                {
                    "state": "MISSING",
                    "symbol": args.symbol,
                    "message": "저장된 활성 종목을 찾을 수 없습니다.",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result.recommendation_computable:
        return 0
    if result.data_state.value == "MISSING":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
