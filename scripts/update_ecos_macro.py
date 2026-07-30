from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.session import create_db_engine, create_session_factory
from app.logging_config import configure_logging, safe_exception_message
from app.models.metadata import DataState
from app.providers.ecos import (
    ECOS_BASE_URL,
    ECOS_SERIES,
    ECOS_SERIES_BY_KEY,
    ECOS_STATISTIC_SEARCH_FUNCTION,
    EcosProvider,
)
from app.repositories.raw_response_repository import RawResponseRepository
from app.utils.dates import now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


def build_parser() -> argparse.ArgumentParser:
    today = now_kst().date()
    parser = argparse.ArgumentParser(
        description="한국은행 ECOS 주요 거시경제 시계열을 수집합니다."
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=today - timedelta(days=30),
        help="조회 시작일(YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=today,
        help="조회 종료일(YYYY-MM-DD)",
    )
    parser.add_argument(
        "--series",
        choices=tuple(ECOS_SERIES_BY_KEY),
        action="append",
        help="조회할 시리즈. 생략하면 기본 3개 시리즈를 모두 조회합니다.",
    )
    return parser


async def _run(arguments: argparse.Namespace) -> int:
    if arguments.start > arguments.end:
        raise ValueError("--start must not be after --end")
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    raw_repository = RawResponseRepository(settings)
    provider = EcosProvider(settings)
    requested = (
        [ECOS_SERIES_BY_KEY[key] for key in arguments.series]
        if arguments.series
        else list(ECOS_SERIES)
    )
    results: list[dict[str, object]] = []
    try:
        for series in requested:
            response = await provider.fetch_series(
                series=series,
                start_date=arguments.start,
                end_date=arguments.end,
            )
            with sessions.begin() as session:
                raw_repository.save(
                    session,
                    provider="ECOS",
                    function_name=(
                        f"{ECOS_STATISTIC_SEARCH_FUNCTION}: {series.label}"
                    ),
                    endpoint=f"{ECOS_BASE_URL}/StatisticSearch",
                    request_parameters={
                        "series": series.key,
                        "stat_code": series.stat_code,
                        "cycle": series.cycle,
                        "item_code": series.item_code,
                        "start_date": arguments.start,
                        "end_date": arguments.end,
                    },
                    response=response,
                )
            payload = response.payload or []
            latest = max(payload, key=lambda item: item.observed_on) if payload else None
            results.append(
                {
                    "series": series.key,
                    "label": series.label,
                    "state": response.state.value,
                    "observations": len(payload),
                    "latest_date": (
                        latest.observed_on.isoformat() if latest else None
                    ),
                    "latest_value": str(latest.value) if latest else None,
                    "unit": latest.unit_name if latest else series.expected_unit,
                    "error_code": response.error_code,
                }
            )
    finally:
        engine.dispose()

    states = {result["state"] for result in results}
    overall = (
        DataState.AVAILABLE.value
        if states == {DataState.AVAILABLE.value}
        else (
            DataState.FETCH_FAILED.value
            if DataState.FETCH_FAILED.value in states
            else DataState.MISSING.value
        )
    )
    print(
        json.dumps(
            {
                "state": overall,
                "start": arguments.start.isoformat(),
                "end": arguments.end.isoformat(),
                "series": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if overall == DataState.AVAILABLE.value else 1


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        return asyncio.run(_run(arguments))
    except (SQLAlchemyError, OSError, ValidationError, ValueError) as exc:
        settings = get_settings()
        print(
            json.dumps(
                {
                    "state": DataState.FETCH_FAILED.value,
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
