from __future__ import annotations

import asyncio
import os

from app.config import get_settings
from app.models.realtime_market import (
    RealtimeCollectorState,
    RealtimeCollectorStatus,
    RealtimeIndexTick,
    RealtimeStockTick,
)
from app.providers.kis_realtime import KisRealtimeProvider
from app.services.realtime_market_service import (
    RealtimeMarketAnalyzer,
    RealtimeMarketStore,
    realtime_market_constituents,
)
from app.utils.dates import now_kst


async def run() -> None:
    settings = get_settings()
    store = RealtimeMarketStore(settings.realtime_market_snapshot_path)
    pid = os.getpid()
    store.save_pid(pid)
    analyzer = RealtimeMarketAnalyzer(
        interval_seconds=settings.realtime_market_interval_seconds,
        rule_version=settings.realtime_market_rule_version,
    )
    latest_index: RealtimeIndexTick | None = None
    latest_stocks: dict[str, RealtimeStockTick] = {}
    retry_seconds = 2
    constituents = realtime_market_constituents(settings, limit=12)
    symbols = tuple(item.symbol for item in constituents)
    try:
        while True:
            store.save_status(
                RealtimeCollectorStatus(
                    state=(
                        RealtimeCollectorState.STARTING
                        if latest_index is None
                        else RealtimeCollectorState.RECONNECTING
                    ),
                    updated_at=now_kst(),
                    pid=pid,
                    detail="KIS 실시간 시세 연결 중입니다.",
                )
            )
            try:
                provider = KisRealtimeProvider(settings)
                async for tick in provider.stream(symbols=symbols or None):
                    if isinstance(tick, RealtimeIndexTick):
                        latest_index = tick
                    elif isinstance(tick, RealtimeStockTick):
                        latest_stocks[tick.symbol] = tick
                    if latest_index is None:
                        continue
                    snapshot = analyzer.analyze(latest_index, latest_stocks)
                    store.save_snapshot(snapshot)
                    store.save_status(
                        RealtimeCollectorStatus(
                            state=RealtimeCollectorState.LIVE,
                            updated_at=now_kst(),
                            pid=pid,
                            detail="KIS 실시간 시세 수신 중",
                        )
                    )
                    retry_seconds = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - daemon must reconnect
                store.save_status(
                    RealtimeCollectorStatus(
                        state=RealtimeCollectorState.RECONNECTING,
                        updated_at=now_kst(),
                        pid=pid,
                        detail=f"재연결 대기: {type(exc).__name__}",
                    )
                )
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, 60)
    finally:
        store.save_status(
            RealtimeCollectorStatus(
                state=RealtimeCollectorState.STOPPED,
                updated_at=now_kst(),
                pid=pid,
                detail="실시간 수집기가 종료되었습니다.",
            )
        )
        store.clear_pid(pid)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
