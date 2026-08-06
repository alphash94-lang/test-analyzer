from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.config import Settings
from app.db.models.market import PriceDaily, Stock
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.market_analysis import MarketRegime, ShockClassification
from app.models.metadata import DataState
from app.models.realtime_market import (
    RealtimeCollectorState,
    RealtimeCollectorStatus,
    RealtimeIndexTick,
    RealtimeMarketSnapshot,
    RealtimeStockTick,
)
from app.providers.kis_reference import KisReferenceProvider
from app.utils.dates import ensure_kst, now_kst


@dataclass(frozen=True)
class RealtimeMarketConstituent:
    symbol: str
    name: str
    market_cap: Decimal
    market_weight: Decimal


def realtime_market_constituents(
    settings: Settings,
    *,
    limit: int = 12,
) -> tuple[RealtimeMarketConstituent, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    try:
        with sessions() as session:
            latest_date = session.scalar(
                select(func.max(PriceDaily.trade_date))
                .join(Stock, Stock.id == PriceDaily.stock_id)
                .where(
                    Stock.is_active.is_(True),
                    Stock.is_kospi.is_(True),
                    Stock.share_class == "COMMON",
                    PriceDaily.market_cap.is_not(None),
                    PriceDaily.market_cap > 0,
                )
            )
            if latest_date is None:
                return ()
            rows = session.execute(
                select(
                    Stock.symbol,
                    Stock.name_ko,
                    PriceDaily.market_cap,
                )
                .join(PriceDaily, PriceDaily.stock_id == Stock.id)
                .where(
                    Stock.is_active.is_(True),
                    Stock.is_kospi.is_(True),
                    Stock.share_class == "COMMON",
                    PriceDaily.trade_date == latest_date,
                    PriceDaily.market_cap.is_not(None),
                    PriceDaily.market_cap > 0,
                )
                .order_by(PriceDaily.market_cap.desc())
            ).all()
            latest_by_symbol: dict[str, tuple[str, Decimal]] = {}
            for symbol, name, market_cap in rows:
                latest_by_symbol.setdefault(symbol, (name, market_cap))
            total_market_cap = sum(
                (market_cap for _, market_cap in latest_by_symbol.values()),
                Decimal(0),
            )
            if total_market_cap <= 0:
                return ()
            return tuple(
                RealtimeMarketConstituent(
                    symbol=symbol,
                    name=name,
                    market_cap=market_cap,
                    market_weight=market_cap / total_market_cap,
                )
                for symbol, (name, market_cap) in list(latest_by_symbol.items())[:limit]
            )
    finally:
        dispose_db_engine(engine)


async def refresh_realtime_stock_overlay(
    settings: Settings,
) -> tuple[RealtimeMarketSnapshot | None, tuple[str, ...]]:
    """Refresh top-cap stock rates through KIS REST after stream interruptions."""
    store = RealtimeMarketStore(settings.realtime_market_snapshot_path)
    existing = store.load_snapshot()
    if existing is None:
        return None, ("KOSPI 실시간 지수 스냅샷이 먼저 필요합니다.",)
    constituents = realtime_market_constituents(settings, limit=12)
    provider = KisReferenceProvider(settings)
    stock_ticks: dict[str, RealtimeStockTick] = {}
    errors: list[str] = []
    for item in constituents:
        response = await provider.fetch_current_valuation(symbol=item.symbol)
        if response.state != DataState.AVAILABLE or not response.payload:
            errors.append(f"{item.name} 현재가 미수신")
            continue
        quote = response.payload[0]
        if quote.current_price is None or quote.change_rate is None:
            errors.append(f"{item.name} 등락률 미제공")
            continue
        stock_ticks[item.symbol] = RealtimeStockTick(
            symbol=item.symbol,
            as_of_at=(response.metadata.as_of_at or response.metadata.collected_at),
            price=quote.current_price,
            change_rate=quote.change_rate,
        )
    if not stock_ticks:
        return existing, tuple(errors or ["상위 종목 현재가를 수신하지 못했습니다."])
    analyzer = RealtimeMarketAnalyzer(
        interval_seconds=settings.realtime_market_interval_seconds,
        rule_version=settings.realtime_market_rule_version,
    )
    refreshed = analyzer.analyze(
        RealtimeIndexTick(
            as_of_at=existing.as_of_at,
            level=existing.kospi_level,
            change_rate=existing.kospi_change_rate,
            advancing_count=existing.advancing_count,
            unchanged_count=existing.unchanged_count,
            declining_count=existing.declining_count,
        ),
        stock_ticks,
    )
    store.save_snapshot(refreshed)
    return refreshed, tuple(errors)


class RealtimeMarketStore:
    def __init__(self, snapshot_path: Path) -> None:
        self.snapshot_path = snapshot_path
        self.status_path = snapshot_path.with_name(f"{snapshot_path.stem}.status.json")
        self.pid_path = snapshot_path.with_name(f"{snapshot_path.stem}.pid")

    def load_snapshot(self) -> RealtimeMarketSnapshot | None:
        return self._load(self.snapshot_path, RealtimeMarketSnapshot)

    def save_snapshot(self, snapshot: RealtimeMarketSnapshot) -> None:
        self._save(self.snapshot_path, snapshot.model_dump(mode="json"))

    def load_status(self) -> RealtimeCollectorStatus | None:
        return self._load(self.status_path, RealtimeCollectorStatus)

    def save_status(self, status: RealtimeCollectorStatus) -> None:
        self._save(self.status_path, status.model_dump(mode="json"))

    def load_pid(self) -> int | None:
        try:
            value = int(self.pid_path.read_text(encoding="ascii").strip())
        except OSError, ValueError:
            return None
        return value if value > 0 else None

    def save_pid(self, pid: int) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(pid), encoding="ascii")

    def clear_pid(self, pid: int) -> None:
        if self.load_pid() != pid:
            return
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def process_is_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except OSError, ProcessLookupError:
            return False
        return True

    @staticmethod
    def _load[T: RealtimeMarketSnapshot | RealtimeCollectorStatus](
        path: Path,
        model: type[T],
    ) -> T | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return model.model_validate(payload)
        except OSError, ValueError:
            return None

    @staticmethod
    def _save(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)


class RealtimeMarketAnalyzer:
    """Five-minute provisional overlay; never replaces confirmed daily Phase 3."""

    def __init__(self, *, interval_seconds: int, rule_version: str) -> None:
        self.interval_seconds = interval_seconds
        self.rule_version = rule_version

    def analyze(
        self,
        index: RealtimeIndexTick,
        stocks: dict[str, RealtimeStockTick],
    ) -> RealtimeMarketSnapshot:
        total = index.advancing_count + index.unchanged_count + index.declining_count
        advancing_ratio = (
            Decimal(index.advancing_count) / Decimal(total) if total > 0 else Decimal(0)
        )
        samsung = stocks.get("005930")
        hynix = stocks.get("000660")
        confidence = Decimal(70)
        if samsung is not None:
            confidence += Decimal(15)
        if hynix is not None:
            confidence += Decimal(15)

        rate = index.change_rate
        if rate <= Decimal(-3) or advancing_ratio <= Decimal("0.20"):
            regime = MarketRegime.RED
        elif rate <= Decimal("-1.5") or advancing_ratio <= Decimal("0.35"):
            regime = MarketRegime.ORANGE
        elif rate >= Decimal("0.75") and advancing_ratio >= Decimal("0.60"):
            regime = MarketRegime.GREEN
        else:
            regime = MarketRegime.YELLOW

        semiconductor_rates = [
            tick.change_rate for tick in (samsung, hynix) if tick is not None
        ]
        semiconductor_average = (
            sum(semiconductor_rates, Decimal(0)) / Decimal(len(semiconductor_rates))
            if semiconductor_rates
            else None
        )
        if (
            semiconductor_average is not None
            and semiconductor_average < 0
            and semiconductor_average <= rate - Decimal(1)
        ):
            shock = ShockClassification.SEMICONDUCTOR_LED
        elif rate <= Decimal(-1) and advancing_ratio <= Decimal("0.35"):
            shock = ShockClassification.BROAD_SELLOFF
        else:
            shock = ShockClassification.MIXED

        bucket = self._bucket_start(index.as_of_at)
        explanation = (
            f"KOSPI {rate:+.2f}%, 상승 비율 "
            f"{advancing_ratio * Decimal(100):.1f}%를 핵심 신호로 계산했습니다. "
            "장중 잠정치이며 일봉 확정 Phase 3를 대체하지 않습니다."
        )
        return RealtimeMarketSnapshot(
            as_of_at=index.as_of_at,
            bucket_started_at=bucket,
            market_regime=regime,
            shock_classification=shock,
            confidence=confidence,
            kospi_level=index.level,
            kospi_change_rate=rate,
            advancing_count=index.advancing_count,
            unchanged_count=index.unchanged_count,
            declining_count=index.declining_count,
            advancing_ratio=advancing_ratio,
            samsung_change_rate=(samsung.change_rate if samsung is not None else None),
            sk_hynix_change_rate=(hynix.change_rate if hynix is not None else None),
            stock_change_rates={
                symbol: tick.change_rate for symbol, tick in stocks.items()
            },
            rule_version=self.rule_version,
            explanation=explanation,
        )

    def _bucket_start(self, value: datetime) -> datetime:
        value = ensure_kst(value)
        epoch = int(value.timestamp())
        bucket_epoch = epoch - (epoch % self.interval_seconds)
        return datetime.fromtimestamp(bucket_epoch, tz=value.tzinfo)


def start_realtime_collector(settings: Settings) -> tuple[bool, str]:
    store = RealtimeMarketStore(settings.realtime_market_snapshot_path)
    existing_pid = store.load_pid()
    if store.process_is_alive(existing_pid):
        return False, f"이미 실행 중입니다 (PID {existing_pid})."
    if settings.kis_app_key is None or settings.kis_app_secret is None:
        return False, "KIS_APP_KEY와 KIS_APP_SECRET 설정이 필요합니다."

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    process = subprocess.Popen(
        [sys.executable, "-m", "scripts.run_realtime_market"],
        cwd=Path.cwd(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
    store.save_pid(process.pid)
    store.save_status(
        RealtimeCollectorStatus(
            state=RealtimeCollectorState.STARTING,
            updated_at=now_kst(),
            pid=process.pid,
            detail="KIS 실시간 연결을 시작하고 있습니다.",
        )
    )
    return True, f"실시간 수집기를 시작했습니다 (PID {process.pid})."
