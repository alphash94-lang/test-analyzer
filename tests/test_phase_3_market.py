from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.db.models.financial import Dividend
from app.db.models.market import PriceDaily, Stock, StockClassification
from app.db.models.market_analysis import IndexDaily, MarketRegimeSnapshot
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import (
    BreadthAnalysis,
    ConstituentObservation,
    DividendContagionAnalysis,
    IndexPoint,
    KrxIndexDailyItem,
    ProxyKind,
    SemiconductorAnalysis,
)
from app.models.metadata import DataState, DataTiming
from app.providers.krx_index import KrxIndexDailyProvider
from app.repositories.index_repository import IndexRepository
from app.repositories.phase3_input_repository import (
    Phase3InputBundle,
    Phase3InputRepository,
)
from app.services.dividend_contagion_analyzer import DividendContagionAnalyzer
from app.services.index_service import IndexService
from app.services.market_regime_service import MarketRegimeService
from app.services.market_shock_analyzer import MarketShockAnalyzer
from app.services.semiconductor_contribution_analyzer import (
    SemiconductorContributionAnalyzer,
)
from app.utils.dates import SEOUL
from tests.helpers import make_settings, migrate_database


def index_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "BAS_DD": "20260729",
        "IDX_CLSS": "KOSPI",
        "IDX_NM": "코스피",
        "CLSPRC_IDX": "3,200.50",
        "CMPPREVDD_IDX": "-10.00",
        "FLUC_RT": "-0.31",
        "OPNPRC_IDX": "3,210.00",
        "HGPRC_IDX": "3,220.00",
        "LWPRC_IDX": "3,190.00",
        "ACC_TRDVOL": "1,000",
        "ACC_TRDVAL": "2,000",
        "MKTCAP": "3,000",
    }
    row.update(overrides)
    return row


def observation(
    stock_id: int,
    symbol: str,
    *,
    start: str = "100",
    previous: str = "100",
    close: str = "100",
    market_cap: str = "100",
    semiconductor: bool | None,
    dividend: bool | None = None,
) -> ConstituentObservation:
    as_of_date = date(2026, 7, 29)
    value = Decimal(close)
    return ConstituentObservation(
        stock_id=stock_id,
        symbol=symbol,
        name=f"종목{stock_id}",
        start_date=date(2026, 6, 29),
        previous_date=date(2026, 7, 28),
        as_of_date=as_of_date,
        start_close=Decimal(start),
        previous_close=Decimal(previous),
        close=value,
        start_market_cap=Decimal(market_cap),
        previous_market_cap=Decimal(market_cap),
        close_history=tuple([Decimal(100)] * 59 + [value]),
        is_semiconductor=semiconductor,
        classification_source="KRX" if semiconductor is not None else None,
        is_confirmed_dividend_payer=dividend,
        price_source_provider="KIS",
        market_cap_source_provider="KRX",
        collected_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
    )


def index_points(count: int = 252) -> list[IndexPoint]:
    start = date(2025, 7, 1)
    return [
        IndexPoint(
            trade_date=start + timedelta(days=index),
            close=Decimal(100 + index),
            source_provider="KRX",
            source_function="KOSPI 시리즈 일별시세정보",
            collected_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
        for index in range(count)
    ]


def phase3_bundle(
    *,
    official_points: list[IndexPoint] | None = None,
    observations: list[ConstituentObservation] | None = None,
    proxy_kind: ProxyKind = ProxyKind.SELF_CALCULATED_PROXY,
) -> Phase3InputBundle:
    members = observations or [
        observation(
            1,
            "005930",
            close="110",
            market_cap="100",
            semiconductor=True,
            dividend=True,
        ),
        observation(
            2,
            "000660",
            close="120",
            market_cap="100",
            semiconductor=True,
            dividend=True,
        ),
        observation(
            3,
            "000003",
            close="105",
            market_cap="100",
            semiconductor=False,
        ),
        observation(
            4,
            "000004",
            close="95",
            market_cap="100",
            semiconductor=False,
        ),
    ]
    return Phase3InputBundle(
        index_points=index_points(),
        official_semiconductor_index_points=official_points or [],
        observations=members,
        universe_size=len(members),
        classification_count=sum(
            item.is_semiconductor is not None for item in members
        ),
        proxy_kind=proxy_kind,
    )


def test_krx_index_contract_parses_only_confirmed_fields() -> None:
    item = KrxIndexDailyItem.model_validate(index_row())

    assert item.trade_date == date(2026, 7, 29)
    assert item.close == Decimal("3200.50")
    with pytest.raises(ValueError, match="must not be null"):
        KrxIndexDailyItem.model_validate(index_row(CLSPRC_IDX=None))


def test_index_provider_rejects_mismatched_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"OutBlock_1": [index_row(BAS_DD="20260728")]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KrxIndexDailyProvider(
        make_settings(krx_api_key="test-key"),
        client,
    )
    response = asyncio.run(provider.fetch(as_of_date=date(2026, 7, 29)))
    asyncio.run(client.aclose())

    assert response.state == DataState.FETCH_FAILED
    assert response.payload is None


def test_index_service_does_not_store_http_error_as_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "index-error.db", monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request, json={"error": "failed"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = make_settings(
        database_url=database_url,
        krx_api_key="test-key",
        raw_data_dir=tmp_path / "raw",
    )
    service = IndexService(
        settings,
        provider=KrxIndexDailyProvider(settings, client),
    )
    summary = asyncio.run(service.refresh(date(2026, 7, 29)))
    service.close()
    asyncio.run(client.aclose())
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.query(IndexDaily).count() == 0
    engine.dispose()

    assert summary.state == DataState.FETCH_FAILED.value


def test_highs_keep_high_date_and_drawdown() -> None:
    points = index_points()
    points[-10] = points[-10].model_copy(update={"close": Decimal(500)})

    highs = MarketShockAnalyzer(make_settings()).calculate_highs(points)

    assert highs[21].high == Decimal(500)
    assert highs[21].high_date == points[-10].trade_date
    assert highs[21].drawdown == points[-1].close / Decimal(500) - Decimal(1)
    assert set(highs) == {21, 63, 126, 252}


def test_semiconductor_baskets_and_contributions_are_explainable() -> None:
    settings = make_settings(phase3_minimum_semiconductor_sample=2)
    observations = [
        observation(
            1,
            "005930",
            close="90",
            market_cap="400",
            semiconductor=True,
        ),
        observation(
            2,
            "000660",
            close="90",
            market_cap="100",
            semiconductor=True,
        ),
        observation(
            3,
            "000003",
            close="99",
            market_cap="250",
            semiconductor=False,
        ),
        observation(
            4,
            "000004",
            close="101",
            market_cap="250",
            semiconductor=False,
        ),
    ]

    result = SemiconductorContributionAnalyzer(settings).analyze(
        observations,
        proxy_kind=ProxyKind.SELF_CALCULATED_PROXY,
    )

    assert result.state == DataState.AVAILABLE
    assert result.cap_weighted_return == Decimal("-0.1")
    assert result.equal_weighted_return == Decimal("-0.1")
    assert result.non_semiconductor_equal_weighted_return == Decimal(0)
    assert result.semiconductor_negative_contribution_share == (
        Decimal("0.05") / Decimal("0.0525")
    )
    assert result.samsung_contribution == Decimal("-0.04")
    assert result.sk_hynix_contribution == Decimal("-0.01")


def test_contributions_use_full_universe_denominator_and_keep_unclassified() -> None:
    observations = [
        observation(
            1,
            "005930",
            previous="100",
            close="90",
            market_cap="100",
            semiconductor=True,
        ),
        observation(
            2,
            "000660",
            previous="100",
            close="90",
            market_cap="100",
            semiconductor=True,
        ),
        observation(
            3,
            "000003",
            previous="100",
            close="90",
            market_cap="100",
            semiconductor=False,
        ),
        observation(
            4,
            "000004",
            previous="100",
            close="90",
            market_cap="100",
            semiconductor=False,
        ),
        observation(
            5,
            "000005",
            previous="100",
            close="90",
            market_cap="100",
            semiconductor=None,
        ),
    ]

    result = SemiconductorContributionAnalyzer(
        make_settings(phase3_minimum_semiconductor_sample=2)
    ).analyze(
        observations,
        proxy_kind=ProxyKind.SELF_CALCULATED_PROXY,
    )

    assert result.state == DataState.AVAILABLE
    assert len(result.contributions) == 5
    assert sum(
        (item.previous_weight for item in result.contributions),
        Decimal(0),
    ) == Decimal(1)
    unclassified = next(
        item for item in result.contributions if item.symbol == "000005"
    )
    assert unclassified.is_semiconductor is None
    assert unclassified.market_cap_source_provider == "KRX"
    assert unclassified.data_timing == DataTiming.PREVIOUS_CLOSE
    assert unclassified.proxy_kind == ProxyKind.SELF_CALCULATED_PROXY


def test_missing_official_classification_never_guesses_proxy() -> None:
    result = SemiconductorContributionAnalyzer(
        make_settings(phase3_minimum_semiconductor_sample=2)
    ).analyze(
        [
            observation(1, "005930", semiconductor=None),
            observation(2, "000660", semiconductor=None),
        ],
        proxy_kind=ProxyKind.NOT_AVAILABLE,
    )

    assert result.state == DataState.MISSING
    assert result.proxy_kind == ProxyKind.NOT_AVAILABLE
    assert result.cap_weighted_return is None


def test_dividend_contagion_uses_confirmed_sample_only() -> None:
    analyzer = DividendContagionAnalyzer(
        make_settings(phase3_minimum_dividend_sample=2)
    )
    result = analyzer.analyze(
        [
            observation(
                1,
                "000001",
                close="95",
                semiconductor=False,
                dividend=True,
            ),
            observation(
                2,
                "000002",
                close="97",
                semiconductor=False,
                dividend=True,
            ),
            observation(
                3,
                "000003",
                close="50",
                semiconductor=False,
                dividend=None,
            ),
        ],
        kospi_return=Decimal("-0.08"),
        non_semiconductor_return=Decimal("-0.07"),
    )

    assert result.state == DataState.AVAILABLE
    assert result.dividend_equal_weighted_return == Decimal("-0.04")
    assert result.relative_to_kospi == Decimal("0.04")
    assert result.recovery is True


def test_two_anchor_stocks_alone_do_not_make_green_regime() -> None:
    settings = make_settings()
    analyzer = MarketShockAnalyzer(settings)
    points = index_points()
    highs = analyzer.calculate_highs(points)
    semiconductor = SemiconductorAnalysis(
        state=DataState.AVAILABLE,
        proxy_kind=ProxyKind.SELF_CALCULATED_PROXY,
        cap_weighted_return=Decimal("0.02"),
        equal_weighted_return=Decimal("0.02"),
        non_semiconductor_cap_weighted_return=Decimal("-0.01"),
        non_semiconductor_equal_weighted_return=Decimal("-0.01"),
        non_semiconductor_median_return=Decimal("-0.01"),
        semiconductor_negative_contribution_share=Decimal(0),
        semiconductor_contribution=Decimal("0.01"),
        reason="test",
    )
    dividend = DividendContagionAnalysis(
        state=DataState.AVAILABLE,
        dividend_equal_weighted_return=Decimal("0.01"),
        relative_to_kospi=Decimal("0.01"),
        relative_to_non_semiconductor=Decimal("0.02"),
        sample_size=3,
        recovery=True,
        reason="test",
    )
    breadth = BreadthAnalysis(
        state=DataState.AVAILABLE,
        equal_weighted_return=Decimal("-0.01"),
        median_return=Decimal("-0.01"),
        advancing_ratio=Decimal("0.55"),
        above_sma20_ratio=Decimal("0.40"),
        above_sma60_ratio=Decimal("0.30"),
        advancing_count=55,
        declining_count=45,
        sample_size=100,
        reason="test",
    )

    regime, _, _, non_semiconductor_breadth, _ = analyzer.classify_regime(
        index_points=points,
        highs=highs,
        breadth=breadth,
        semiconductor=semiconductor,
        dividend=dividend,
    )

    assert regime.value != "GREEN"
    assert non_semiconductor_breadth is False


def test_input_hash_covers_histories_official_index_and_all_rule_settings() -> None:
    settings = make_settings(
        phase3_minimum_constituents=4,
        phase3_minimum_semiconductor_sample=2,
        phase3_minimum_dividend_sample=2,
    )
    service = MarketRegimeService(settings)
    try:
        base = phase3_bundle()
        history_changed_members = list(base.observations)
        history_changed_members[0] = history_changed_members[0].model_copy(
            update={
                "close_history": tuple(
                    [Decimal(80)] * 59 + [Decimal(110)]
                )
            }
        )
        history_changed = phase3_bundle(observations=history_changed_members)
        official_changed = phase3_bundle(
            official_points=[
                point.model_copy(update={"close": point.close + Decimal(7)})
                for point in index_points(22)
            ]
        )
        hashes = {
            service._input_hash(base),
            service._input_hash(history_changed),
            service._input_hash(official_changed),
        }
    finally:
        service.close()

    changed_rule_service = MarketRegimeService(
        settings.model_copy(
            update={"phase3_green_breadth20": Decimal("0.75")}
        )
    )
    try:
        hashes.add(changed_rule_service._input_hash(base))
    finally:
        changed_rule_service.close()

    assert len(hashes) == 4


def test_official_semiconductor_index_requires_aligned_window() -> None:
    settings = make_settings(
        phase3_minimum_constituents=4,
        phase3_minimum_semiconductor_sample=2,
        phase3_minimum_dividend_sample=2,
        phase3_semiconductor_classification_codes="SEMICONDUCTOR",
    )
    stale_official = [
        point.model_copy(
            update={
                "trade_date": point.trade_date - timedelta(days=1),
                "close": Decimal(100 + offset),
            }
        )
        for offset, point in enumerate(index_points(22))
    ]
    service = MarketRegimeService(settings)
    try:
        result = service._analyze(
            phase3_bundle(
                official_points=stale_official,
                proxy_kind=ProxyKind.OFFICIAL_INDEX,
            ),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    finally:
        service.close()

    metrics = {metric.code: metric for metric in result.metrics}
    assert result.proxy_kind == ProxyKind.SELF_CALCULATED_PROXY
    assert metrics["SEMICONDUCTOR_CAP_RETURN"].proxy_kind == (
        ProxyKind.SELF_CALCULATED_PROXY
    )
    assert metrics["KOSPI_CURRENT"].proxy_kind == ProxyKind.NOT_APPLICABLE
    assert all(
        metric.data_timing == DataTiming.PREVIOUS_CLOSE
        for metric in result.metrics
    )


def test_official_index_provenance_applies_only_to_official_cap_return() -> None:
    settings = make_settings(
        phase3_minimum_constituents=4,
        phase3_minimum_semiconductor_sample=2,
        phase3_minimum_dividend_sample=2,
        phase3_semiconductor_classification_codes="SEMICONDUCTOR",
    )
    bundle = phase3_bundle()
    official = [
        point.model_copy(update={"close": Decimal(100 + offset)})
        for offset, point in enumerate(bundle.index_points[-22:])
    ]
    service = MarketRegimeService(settings)
    try:
        result = service._analyze(
            phase3_bundle(
                official_points=official,
                proxy_kind=ProxyKind.OFFICIAL_INDEX,
            ),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    finally:
        service.close()

    metrics = {metric.code: metric for metric in result.metrics}
    cap_return = metrics["SEMICONDUCTOR_CAP_RETURN"]
    equal_return = metrics["SEMICONDUCTOR_EQUAL_RETURN"]
    contribution = metrics["SEMICONDUCTOR_CONTRIBUTION"]

    assert result.proxy_kind == ProxyKind.OFFICIAL_INDEX
    assert cap_return.proxy_kind == ProxyKind.OFFICIAL_INDEX
    assert cap_return.source_provider == "KRX"
    assert cap_return.collected_at == official[-1].collected_at
    assert equal_return.proxy_kind == ProxyKind.SELF_CALCULATED_PROXY
    assert contribution.proxy_kind == ProxyKind.SELF_CALCULATED_PROXY


def test_index_history_does_not_mix_unconfigured_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "index-source.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        for provider, trade_date, close, timing in (
            (
                "KRX",
                date(2026, 7, 29),
                Decimal(100),
                DataTiming.PREVIOUS_CLOSE,
            ),
            (
                "OTHER",
                date(2026, 7, 29),
                Decimal(999),
                DataTiming.PREVIOUS_CLOSE,
            ),
            (
                "KRX",
                date(2026, 7, 28),
                Decimal(777),
                DataTiming.DELAYED,
            ),
        ):
            session.add(
                IndexDaily(
                    index_class="KOSPI",
                    index_name="코스피",
                    trade_date=trade_date,
                    close=close,
                    previous_day_change=Decimal(1),
                    fluctuation_rate=Decimal(1),
                    open=close,
                    high=close,
                    low=close,
                    volume=Decimal(1),
                    trading_value=Decimal(1),
                    market_cap=Decimal(1),
                    source_provider=provider,
                    source_function="test source",
                    data_state=DataState.AVAILABLE.value,
                    as_of_at=as_of_at,
                    collected_at=as_of_at,
                    data_timing=timing.value,
                )
            )
    with sessions() as session:
        points = IndexRepository().history(
            session,
            "코스피",
            as_of_date=date(2026, 7, 29),
            as_of_at=as_of_at,
            limit=10,
        )
    engine.dispose()

    assert [(point.source_provider, point.close) for point in points] == [
        ("KRX", Decimal(100))
    ]


def test_adjusted_price_market_cap_is_not_used_as_official_market_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "market-cap-source.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_date = date(2026, 7, 29)
    collected_at = datetime(2026, 7, 29, 17, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        session.add(
            IndexDaily(
                index_class="KOSPI",
                index_name="코스피",
                trade_date=as_of_date,
                close=Decimal(3000),
                previous_day_change=Decimal(1),
                fluctuation_rate=Decimal(1),
                open=Decimal(3000),
                high=Decimal(3000),
                low=Decimal(3000),
                volume=Decimal(1),
                trading_value=Decimal(1),
                market_cap=Decimal(1),
                source_provider="KRX",
                source_function="KOSPI 시리즈 일별시세정보",
                data_state=DataState.AVAILABLE.value,
                as_of_at=collected_at,
                collected_at=collected_at,
                data_timing=DataTiming.PREVIOUS_CLOSE.value,
            )
        )
        stock = Stock(
            symbol="000001",
            name_ko="시장종목",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            universe_status="REVIEW_REQUIRED",
            quality_state="VALID",
            is_active=True,
            source_provider="KRX",
            source_function="유가증권 종목기본정보",
            data_state=DataState.AVAILABLE.value,
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing=DataTiming.NOT_APPLICABLE.value,
        )
        session.add(stock)
        session.flush()
        for offset in range(61):
            trade_date = as_of_date - timedelta(days=60 - offset)
            session.add(
                PriceDaily(
                    stock_id=stock.id,
                    trade_date=trade_date,
                    close_price=Decimal(100 + offset),
                    high_price=Decimal(100 + offset),
                    low_price=Decimal(100 + offset),
                    market_cap=Decimal(1000),
                    is_adjusted=True,
                    adjustment_status="VERIFIED",
                    source_provider="KIS",
                    source_function="국내주식기간별시세",
                    data_state=DataState.AVAILABLE.value,
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing=DataTiming.PREVIOUS_CLOSE.value,
                )
            )
    with sessions() as session:
        bundle = Phase3InputRepository(settings).load(
            session,
            as_of_date=as_of_date,
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    engine.dispose()

    assert bundle.observations == []


def test_dividend_payer_selection_respects_latest_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "dividend-correction.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 17, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        stock = Stock(
            symbol="000001",
            name_ko="배당정정종목",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            universe_status="REVIEW_REQUIRED",
            quality_state="VALID",
            is_active=True,
            source_provider="KRX",
            source_function="유가증권 종목기본정보",
            data_state=DataState.AVAILABLE.value,
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing=DataTiming.NOT_APPLICABLE.value,
        )
        session.add(stock)
        session.flush()
        for receipt_no, filing_date, dps, is_correction in (
            ("20260301000001", date(2026, 3, 1), Decimal(1000), False),
            ("20260302000001", date(2026, 3, 2), Decimal(0), True),
        ):
            session.add(
                Dividend(
                    stock_id=stock.id,
                    receipt_no=receipt_no,
                    business_year=2025,
                    stock_kind="보통주",
                    dividend_type="CASH_DPS",
                    dps=dps,
                    currency="KRW",
                    filing_date=filing_date,
                    is_confirmed=True,
                    is_estimate=False,
                    is_correction=is_correction,
                    source_provider="OpenDART",
                    source_function="배당에 관한 사항",
                    data_state=DataState.AVAILABLE.value,
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing=DataTiming.PERIODIC_DISCLOSURE.value,
                )
            )
        stock_id = stock.id
    with sessions() as session:
        payers = Phase3InputRepository._dividend_payers(
            session,
            stock_ids=[stock_id],
            as_of_date=date(2026, 7, 29),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    engine.dispose()

    assert payers == set()


def test_conflicting_active_classifications_are_not_selected_arbitrarily(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / "classification-conflict.db",
        monkeypatch,
    )
    settings = make_settings(
        database_url=database_url,
        phase3_semiconductor_classification_codes="SEMICONDUCTOR",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 29, 17, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        stock = Stock(
            symbol="000001",
            name_ko="분류충돌종목",
            is_kospi=True,
            security_type="STOCK",
            share_class="COMMON",
            listing_status="LISTED",
            universe_status="REVIEW_REQUIRED",
            quality_state="VALID",
            is_active=True,
            source_provider="KRX",
            source_function="유가증권 종목기본정보",
            data_state=DataState.AVAILABLE.value,
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing=DataTiming.NOT_APPLICABLE.value,
        )
        session.add(stock)
        session.flush()
        for code in ("SEMICONDUCTOR", "OTHER"):
            session.add(
                StockClassification(
                    stock_id=stock.id,
                    classification_system="KRX_INDUSTRY",
                    classification_code=code,
                    classification_name=code,
                    valid_from=date(2026, 1, 1),
                    source_provider="KRX",
                    source_function="official classification",
                    data_state=DataState.AVAILABLE.value,
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing=DataTiming.NOT_APPLICABLE.value,
                )
            )
        stock_id = stock.id
    with sessions() as session:
        classifications = Phase3InputRepository(settings)._classifications(
            session,
            stock_ids=[stock_id],
            as_of_date=date(2026, 7, 29),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    engine.dispose()

    assert stock_id not in classifications


def test_empty_database_stores_uncertain_without_fake_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase3-empty.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    service = MarketRegimeService(settings)
    try:
        result = service.analyze_and_store(
            as_of_date=date(2026, 7, 29),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    finally:
        service.close()

    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        snapshot = session.query(MarketRegimeSnapshot).one()
    engine.dispose()

    assert result.state == DataState.MISSING
    assert result.market_regime.value == "UNCERTAIN"
    assert result.shock_classification.value == "UNCERTAIN"
    assert all(metric.value is None for metric in result.metrics if metric.state != DataState.AVAILABLE)
    assert all(
        metric.data_timing == DataTiming.UNKNOWN
        for metric in result.metrics
        if metric.state != DataState.AVAILABLE
    )
    assert snapshot.data_state == DataState.MISSING.value


def test_full_phase3_input_is_reproducible_and_uses_verified_prices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "phase3-full.db", monkeypatch)
    settings = make_settings(
        database_url=database_url,
        phase3_minimum_constituents=4,
        phase3_minimum_semiconductor_sample=2,
        phase3_minimum_dividend_sample=2,
        phase3_semiconductor_classification_codes="SEMICONDUCTOR",
    )
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    as_of_date = date(2026, 7, 29)
    collected_at = datetime(2026, 7, 29, 17, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        for offset in range(252):
            trade_date = as_of_date - timedelta(days=251 - offset)
            level = Decimal(3000 + offset)
            session.add(
                IndexDaily(
                    index_class="KOSPI",
                    index_name="코스피",
                    trade_date=trade_date,
                    close=level,
                    previous_day_change=Decimal(1),
                    fluctuation_rate=Decimal("0.03"),
                    open=level,
                    high=level,
                    low=level,
                    volume=Decimal(1000),
                    trading_value=Decimal(2000),
                    market_cap=Decimal(3000),
                    source_provider="KRX",
                    source_function="KOSPI 시리즈 일별시세정보",
                    data_state="AVAILABLE",
                    as_of_at=datetime.combine(
                        trade_date,
                        datetime.min.time(),
                        tzinfo=SEOUL,
                    ),
                    collected_at=collected_at,
                    data_timing="PREVIOUS_CLOSE",
                )
            )
        stocks: list[Stock] = []
        for index in range(4):
            stock = Stock(
                symbol=f"{index + 1:06d}",
                name_ko=f"시장종목{index + 1}",
                is_kospi=True,
                security_type="STOCK",
                share_class="COMMON",
                listing_status="LISTED",
                universe_status="REVIEW_REQUIRED",
                quality_state="VALID",
                is_active=True,
                source_provider="KRX",
                source_function="유가증권 종목기본정보",
                data_state="AVAILABLE",
                as_of_at=collected_at,
                collected_at=collected_at,
                data_timing="NOT_APPLICABLE",
            )
            session.add(stock)
            stocks.append(stock)
        session.flush()
        for index, stock in enumerate(stocks):
            session.add(
                StockClassification(
                    stock_id=stock.id,
                    classification_system="KRX_INDUSTRY",
                    classification_code=(
                        "SEMICONDUCTOR" if index < 2 else "OTHER"
                    ),
                    classification_name="반도체" if index < 2 else "기타",
                    valid_from=date(2026, 1, 1),
                    source_provider="KRX",
                    source_function="official test fixture",
                    data_state="AVAILABLE",
                    as_of_at=collected_at,
                    collected_at=collected_at,
                    data_timing="NOT_APPLICABLE",
                )
            )
            for offset in range(61):
                trade_date = as_of_date - timedelta(days=60 - offset)
                close = Decimal(100 + offset + index)
                session.add(
                    PriceDaily(
                        stock_id=stock.id,
                        trade_date=trade_date,
                        close_price=close,
                        high_price=close,
                        low_price=close,
                        market_cap=Decimal(1000 + index * 100),
                        is_adjusted=True,
                        adjustment_status="VERIFIED",
                        source_provider="KIS",
                        source_function="국내주식기간별시세",
                        data_state="AVAILABLE",
                        as_of_at=datetime.combine(
                            trade_date,
                            datetime.min.time(),
                            tzinfo=SEOUL,
                        ),
                        collected_at=collected_at,
                        data_timing="PREVIOUS_CLOSE",
                    )
                )
                if offset in {39, 59}:
                    session.add(
                        PriceDaily(
                            stock_id=stock.id,
                            trade_date=trade_date,
                            market_cap=Decimal(1000 + index * 100),
                            is_adjusted=None,
                            adjustment_status="NOT_VERIFIED",
                            source_provider="KRX",
                            source_function="유가증권 일별매매정보",
                            data_state="AVAILABLE",
                            as_of_at=datetime.combine(
                                trade_date,
                                datetime.min.time(),
                                tzinfo=SEOUL,
                            ),
                            collected_at=collected_at,
                            data_timing="PREVIOUS_CLOSE",
                        )
                    )
            if index < 2:
                session.add(
                    Dividend(
                        stock_id=stock.id,
                        receipt_no=f"202603{index + 1:08d}",
                        business_year=2025,
                        dividend_type="현금배당",
                        dps=Decimal(1000),
                        currency="KRW",
                        filing_date=date(2026, 3, 1 + index),
                        is_confirmed=True,
                        is_estimate=False,
                        source_provider="OpenDART",
                        source_function="배당에 관한 사항",
                        data_state="AVAILABLE",
                        as_of_at=collected_at,
                        collected_at=collected_at,
                        data_timing="OFFICIAL_FILING",
                    )
                )
    engine.dispose()

    service = MarketRegimeService(settings)
    try:
        first = service.analyze_and_store(
            as_of_date=as_of_date,
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
        second = service.analyze_and_store(
            as_of_date=as_of_date,
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    finally:
        service.close()
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions() as session:
        snapshot_count = session.query(MarketRegimeSnapshot).count()
    engine.dispose()

    assert first.state == DataState.AVAILABLE
    assert first.data_confidence == Decimal(100)
    assert first.proxy_kind == ProxyKind.SELF_CALCULATED_PROXY
    assert first.input_data_hash == second.input_data_hash
    assert snapshot_count == 1
