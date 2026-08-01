# pyright: reportArgumentType=false
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.providers.kis_reference import KisReferenceProvider
from app.services.market_screening_service import MarketScreeningService
from app.utils.dates import SEOUL


def _stock(stock_id: int, symbol: str) -> SimpleNamespace:
    return SimpleNamespace(id=stock_id, symbol=symbol)


def _prices(*, start: Decimal, daily_change: Decimal) -> list[SimpleNamespace]:
    rows = []
    current = start
    first_date = date(2026, 5, 1)
    for offset in range(61):
        current *= Decimal(1) + daily_change
        rows.append(
            SimpleNamespace(
                trade_date=first_date + timedelta(days=offset),
                close_price=current,
                trading_value=Decimal(10_000_000_000 + offset),
            )
        )
    return rows


def test_full_market_screen_scores_every_stock_and_rewards_lower_valuation() -> None:
    service = MarketScreeningService()
    as_of = datetime(2026, 7, 30, 18, tzinfo=SEOUL)
    population = [Decimal(5), Decimal(10), Decimal(20)]
    common = {
        "industry": "기계",
        "per_values": population,
        "pbr_values": [Decimal("0.5"), Decimal(1), Decimal(2)],
        "liquidities": [Decimal(1_000_000_000), Decimal(10_000_000_000)],
        "volatilities": [Decimal("0.01"), Decimal("0.03")],
        "returns_60": [Decimal("-0.1"), Decimal("0.1")],
        "as_of_at": as_of,
    }
    cheap = service._score(
        _stock(1, "000001"),
        _prices(start=Decimal(100), daily_change=Decimal("-0.001")),
        per=Decimal(5),
        pbr=Decimal("0.5"),
        **common,
    )
    expensive = service._score(
        _stock(2, "000002"),
        _prices(start=Decimal(100), daily_change=Decimal("0.001")),
        per=Decimal(20),
        pbr=Decimal(2),
        **common,
    )

    assert cheap.investment_score > expensive.investment_score
    assert cheap.individual_entry_score is not None
    assert expensive.individual_entry_score is not None
    assert "현재 PER 5배" in cheap.components[0].explanation


def test_missing_official_valuation_is_zero_scored_but_still_rankable() -> None:
    result = MarketScreeningService()._score(
        _stock(3, "000003"),
        _prices(start=Decimal(100), daily_change=Decimal(0)),
        per=None,
        pbr=None,
        industry=None,
        per_values=[Decimal(10)],
        pbr_values=[Decimal(1)],
        liquidities=[Decimal(10_000_000_000)],
        volatilities=[Decimal(0)],
        returns_60=[Decimal(0)],
        as_of_at=datetime(2026, 7, 30, 18, tzinfo=SEOUL),
    )

    assert result.investment_score is not None
    assert result.individual_entry_score is not None
    assert result.components[0].normalized_value == 0
    assert result.components[1].normalized_value == 0
    assert result.data_confidence == Decimal("50.000")


def test_latest_reported_loss_invalidates_positive_market_per() -> None:
    result = MarketScreeningService()._score(
        _stock(4, "446070"),
        _prices(start=Decimal(100), daily_change=Decimal(0)),
        per=Decimal("5.06"),
        pbr=Decimal("0.16"),
        industry="WOOD",
        per_values=[Decimal(5), Decimal(10), Decimal(20)],
        pbr_values=[Decimal("0.16"), Decimal(1), Decimal(2)],
        liquidities=[Decimal(10_000_000_000)],
        volatilities=[Decimal(0)],
        returns_60=[Decimal(0)],
        as_of_at=datetime(2026, 7, 31, 18, tzinfo=SEOUL),
        latest_net_income=Decimal(-1462252336),
        latest_profit_period=date(2026, 3, 31),
    )

    per_component = next(
        item for item in result.components if item.code == "SCREEN_PER"
    )
    assert per_component.raw_value == Decimal("5.06")
    assert per_component.normalized_value == 0
    assert per_component.contribution == 0
    assert "최신 공시" in per_component.explanation
    assert "제외" in per_component.explanation
    assert result.data_confidence == Decimal("80.000")


def test_kis_accepts_official_six_character_alphanumeric_issue_code() -> None:
    KisReferenceProvider._validate_request(
        "0120G0",
        date(2026, 7, 30),
        date(2026, 7, 30),
    )
