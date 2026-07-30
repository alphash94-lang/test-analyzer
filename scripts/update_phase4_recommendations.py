from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging
from app.services.recommendation_service import RecommendationService
from app.utils.dates import SEOUL, now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "저장된 실제 KOSPI 유니버스 전체에 Phase 2·3과 "
            "포트폴리오 한도를 적용해 읽기 전용 Phase 4 추천을 저장합니다."
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
    as_of_at = min(
        datetime.combine(as_of_date, time.max, tzinfo=SEOUL),
        now_kst(),
    )
    service = RecommendationService(settings)
    try:
        result = service.run_universe(as_of_at=as_of_at)
    finally:
        service.close()
    print(
        json.dumps(
            {
                "state": result.state.value,
                "run_id": result.run_id,
                "analyzed_at": result.analyzed_at.isoformat(),
                "data_basis_date": result.basis_date.isoformat(),
                "score_version": result.score_version,
                "rule_version": result.rule_version,
                "market_rule_version": result.market_rule_version,
                "config_hash": result.config_hash,
                "input_data_hash": result.input_data_hash,
                "total_count": result.total_count,
                "processed_count": result.processed_count,
                "recommended_count": result.recommended_count,
                "excluded_count": result.excluded_count,
                "insufficient_count": result.insufficient_count,
                "market_regime": result.market_regime.value,
                "missing_core_data": list(result.missing_core_data),
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
    except (SQLAlchemyError, OSError, ValueError, ValidationError) as exc:
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
