from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from app.config import get_settings
from app.services.phase3_data_service import Phase3DataService
from app.utils.dates import now_kst


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


async def _run(as_of_date: date) -> int:
    service = Phase3DataService(get_settings())
    try:
        summary = await service.refresh(as_of_date=as_of_date)
    finally:
        service.close()
    print(
        json.dumps(
            {
                "state": summary.state.value,
                "as_of": summary.as_of_date.isoformat(),
                "classifications_stored": summary.classifications_stored,
                "index_dates": summary.index_dates,
                "price_dates": summary.price_dates,
                "errors": summary.errors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary.state == "AVAILABLE" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase3 KOSPI 지수·구성종목·반도체 분류 입력을 백필합니다."
    )
    parser.add_argument("--as-of", type=_parse_date, default=now_kst().date())
    args = parser.parse_args()
    return asyncio.run(_run(args.as_of))


if __name__ == "__main__":
    raise SystemExit(main())
