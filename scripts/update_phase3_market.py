from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging
from app.services.market_regime_service import MarketRegimeService
from app.utils.dates import SEOUL, now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "저장된 공식 지수·분류·배당과 검증된 수정가격으로 "
            "Phase 3 시장국면을 계산합니다."
        )
    )
    parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=now_kst().date(),
        help="분석 기준일(YYYY-MM-DD). 기본값은 실행일 KST입니다.",
    )
    return parser


def _run(as_of_date: date) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    end_of_day = datetime.combine(as_of_date, time.max, tzinfo=SEOUL)
    as_of_at = min(end_of_day, now_kst())
    service = MarketRegimeService(settings)
    try:
        result = service.analyze_and_store(
            as_of_date=as_of_date,
            as_of_at=as_of_at,
        )
    finally:
        service.close()
    print(
        json.dumps(
            {
                "state": result.state.value,
                "as_of_at": result.as_of_at.isoformat(),
                "shock_classification": result.shock_classification.value,
                "market_regime": result.market_regime.value,
                "data_confidence": (
                    str(result.data_confidence)
                    if result.data_confidence is not None
                    else None
                ),
                "proxy_kind": result.proxy_kind.value,
                "missing_core_data": list(result.missing_core_data),
                "rule_version": result.rule_version,
                "input_data_hash": result.input_data_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.state.value == "AVAILABLE" else 2


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        return _run(arguments.as_of)
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
