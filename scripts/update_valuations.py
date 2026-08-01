from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date

from app.config import get_settings
from app.services.valuation_data_service import ValuationDataService

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


async def _run(symbols: list[str], as_of_date: date) -> int:
    service = ValuationDataService(get_settings())
    try:
        summaries = [
            await service.refresh(symbol=symbol, as_of_date=as_of_date)
            for symbol in dict.fromkeys(symbols)
        ]
    finally:
        service.close()
    state = (
        "AVAILABLE"
        if all(summary.state == "AVAILABLE" for summary in summaries)
        else "MISSING"
    )
    print(
        json.dumps(
            {
                "state": state,
                "as_of": as_of_date.isoformat(),
                "summaries": [
                    {
                        "symbol": item.symbol,
                        "state": item.state.value,
                        "current_metrics_stored": item.current_metrics_stored,
                        "industry_samples": item.industry_samples,
                        "historical_metrics_stored": (
                            item.historical_metrics_stored
                        ),
                        "profiles_checked": item.profiles_checked,
                        "errors": item.errors,
                    }
                    for item in summaries
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if state == "AVAILABLE" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KIS·KRX·OpenDART 공식 PER/PBR 비교 데이터를 갱신합니다."
    )
    parser.add_argument("--symbol", required=True, action="append", type=_parse_symbol)
    parser.add_argument("--as-of", required=True, type=_parse_date)
    args = parser.parse_args()
    return asyncio.run(_run(args.symbol, args.as_of))


if __name__ == "__main__":
    raise SystemExit(main())
