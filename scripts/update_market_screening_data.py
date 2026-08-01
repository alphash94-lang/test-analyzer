from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from app.config import get_settings
from app.models.metadata import DataState
from app.services.market_screening_data_service import (
    MarketScreeningDataService,
)
from app.utils.dates import now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


async def _run(as_of_date: date) -> int:
    service = MarketScreeningDataService(get_settings())
    try:
        summary = await service.refresh(as_of_date=as_of_date)
    finally:
        service.close()
    print(
        json.dumps(
            {
                "state": summary.state.value,
                "total": summary.total,
                "processed": summary.processed,
                "per_stored": summary.per_stored,
                "pbr_stored": summary.pbr_stored,
                "industries_stored": summary.industries_stored,
                "failed": summary.failed,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary.state == DataState.AVAILABLE else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KOSPI 보통주 전체의 KIS PER·PBR·업종을 수집합니다."
    )
    parser.add_argument("--as-of", type=_parse_date, default=now_kst().date())
    args = parser.parse_args()
    return asyncio.run(_run(args.as_of))


if __name__ == "__main__":
    raise SystemExit(main())
