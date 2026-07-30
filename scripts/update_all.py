from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.services.event_watchlist_service import EventWatchlistService
from app.utils.dates import now_kst

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_SYMBOL = "005930"


@dataclass(frozen=True)
class UpdateStep:
    name: str
    module: str
    arguments: tuple[str, ...]


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD입니다.") from exc


def _parse_symbol(value: str) -> str:
    normalized = value.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise argparse.ArgumentTypeError("종목코드는 6자리 숫자여야 합니다.")
    return normalized


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "종목·가격·지수·공시·뉴스·KIS·ECOS 데이터를 순서대로 갱신합니다."
        )
    )
    parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=_previous_weekday(now_kst().date()),
        help="수집 기준일(YYYY-MM-DD). 기본값은 직전 평일 KST입니다.",
    )
    parser.add_argument(
        "--symbol",
        type=_parse_symbol,
        action="append",
        help=(
            "공시·뉴스·KIS를 수집할 6자리 종목코드입니다. 여러 번 지정할 수 "
            "있으며, 생략하면 저장된 관심종목을 사용합니다. 관심종목이 "
            f"비어 있으면 {DEFAULT_EVENT_SYMBOL}을 사용합니다."
        ),
    )
    parser.add_argument(
        "--ecos-days",
        type=int,
        default=30,
        help="ECOS 조회기간 일수입니다. 기본값은 30일입니다.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="한 단계가 실패하면 이후 단계를 실행하지 않습니다.",
    )
    return parser


def build_steps(
    *,
    as_of_date: date,
    symbols: list[str],
    ecos_days: int,
) -> list[UpdateStep]:
    if ecos_days < 1:
        raise ValueError("ecos_days must be positive")
    as_of = as_of_date.isoformat()
    ecos_start = (as_of_date - timedelta(days=ecos_days)).isoformat()
    steps = [
        UpdateStep(
            name="stock_master",
            module="scripts.update_stock_master",
            arguments=("--as-of", as_of),
        ),
        UpdateStep(
            name="daily_prices",
            module="scripts.update_daily_prices",
            arguments=("--as-of", as_of),
        ),
        UpdateStep(
            name="daily_index",
            module="scripts.update_daily_index",
            arguments=("--as-of", as_of),
        ),
    ]
    steps.extend(
        UpdateStep(
            name=f"events_{symbol}",
            module="scripts.update_phase5_events",
            arguments=("--symbol", symbol, "--as-of", as_of),
        )
        for symbol in symbols
    )
    steps.append(
        UpdateStep(
            name="ecos_macro",
            module="scripts.update_ecos_macro",
            arguments=("--start", ecos_start, "--end", as_of),
        )
    )
    return steps


def _last_json_object(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_pipeline(
    steps: list[UpdateStep],
    *,
    stop_on_error: bool = False,
    runner: CommandRunner = subprocess.run,
) -> tuple[int, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    failed = False
    for step in steps:
        command = [sys.executable, "-m", step.module, *step.arguments]
        completed = runner(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        payload = _last_json_object(completed.stdout)
        result: dict[str, Any] = {
            "step": step.name,
            "module": step.module,
            "returncode": completed.returncode,
            "state": (
                str(payload.get("state", "UNKNOWN"))
                if payload is not None
                else "UNKNOWN"
            ),
        }
        if payload is not None:
            result["result"] = payload
        elif completed.returncode != 0:
            result["error"] = "하위 수집 명령이 구조화된 결과 없이 실패했습니다."
        results.append(result)
        if completed.returncode != 0:
            failed = True
            if stop_on_error:
                break
    return (1 if failed else 0), results


def resolve_event_symbols(explicit_symbols: list[str] | None) -> list[str]:
    if explicit_symbols:
        return list(dict.fromkeys(explicit_symbols))
    service = EventWatchlistService(get_settings())
    try:
        watchlist_symbols = service.symbols()
    finally:
        service.close()
    return watchlist_symbols or [DEFAULT_EVENT_SYMBOL]


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        symbols = resolve_event_symbols(arguments.symbol)
        steps = build_steps(
            as_of_date=arguments.as_of,
            symbols=symbols,
            ecos_days=arguments.ecos_days,
        )
        returncode, results = run_pipeline(
            steps,
            stop_on_error=arguments.stop_on_error,
        )
        print(
            json.dumps(
                {
                    "state": "AVAILABLE" if returncode == 0 else "FETCH_FAILED",
                    "as_of": arguments.as_of.isoformat(),
                    "symbols": symbols,
                    "steps_completed": len(results),
                    "steps_planned": len(steps),
                    "steps": results,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return returncode
    except (OSError, SQLAlchemyError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "state": "FETCH_FAILED",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
