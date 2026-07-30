from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Numeric, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.db.models  # noqa: F401
from app.config import get_settings
from app.db.base import Base
from app.services.connection_status import REQUIRED_TABLES
from tests.helpers import migrate_database


def test_model_metadata_contains_required_tables() -> None:
    assert REQUIRED_TABLES <= set(Base.metadata.tables)
    assert len(REQUIRED_TABLES) == 37


def test_money_and_missing_values_use_numeric_nullable_columns() -> None:
    price_table = Base.metadata.tables["price_daily"]
    account_table = Base.metadata.tables["financial_accounts"]

    assert isinstance(price_table.c.close_price.type, Numeric)
    assert price_table.c.close_price.nullable is True
    assert isinstance(account_table.c.amount.type, Numeric)
    assert account_table.c.amount.nullable is True


def test_alembic_upgrade_creates_required_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "nested" / "phase0b.db"
    database_url = migrate_database(database_path, monkeypatch)
    engine = create_engine(database_url)

    assert database_path.exists()
    assert REQUIRED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "t6i9j0k1l2m3"
        )
        stock_columns = {
            column["name"] for column in inspect(engine).get_columns("stocks")
        }
        assert {
            "is_kospi",
            "dart_collected_at",
            "dart_data_state",
        } <= stock_columns
        score_columns = {
            column["name"]
            for column in inspect(engine).get_columns("score_snapshots")
        }
        assert {
            "score_scope",
            "individual_entry_score",
            "filter_state",
            "recommendation_computable",
            "missing_core_data",
            "explanation",
        } <= score_columns
        assert {
            "forced_filter_results",
            "score_components",
            "valuation_comparisons",
            "index_daily",
            "market_regime_snapshots",
            "market_metric_records",
            "market_contribution_records",
            "recommendation_runs",
            "recommendation_reasons",
            "split_buy_plans",
            "portfolio_settings",
            "portfolio_positions",
            "portfolio_allocations",
            "news_articles",
            "event_records",
            "analyst_opinions",
            "earnings_estimates",
            "investor_flows",
            "program_trading",
            "short_selling",
            "backtest_runs",
        } <= set(inspect(engine).get_table_names())
        disclosure_columns = {
            column["name"]
            for column in inspect(engine).get_columns("disclosures")
        }
        assert "correction_link_state" in disclosure_columns
        recommendation_columns = {
            column["name"]
            for column in inspect(engine).get_columns("recommendations")
        }
        assert {
            "recommendation_run_id",
            "market_regime_snapshot_id",
            "analyzed_at",
            "data_basis_date",
            "recommendation_label",
            "market_rule_version",
            "config_hash",
            "raw_metrics",
            "filter_results",
            "positive_reasons",
            "risk_reasons",
            "exclusion_reasons",
            "missing_data",
        } <= recommendation_columns
        recommendation_unique_constraints = {
            item["name"]: tuple(item["column_names"])
            for item in inspect(engine).get_unique_constraints(
                "recommendations"
            )
        }
        assert recommendation_unique_constraints[
            "uq_recommendation_reproducible"
        ] == (
            "stock_id",
            "as_of_at",
            "score_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
        )
        portfolio_setting_columns = {
            column["name"]
            for column in inspect(engine).get_columns("portfolio_settings")
        }
        assert "selected_at" in portfolio_setting_columns
        split_buy_columns = {
            column["name"]
            for column in inspect(engine).get_columns("split_buy_plans")
        }
        assert {
            "reference_price_collected_at",
            "reference_price_timing",
        } <= split_buy_columns
        metric_columns = {
            column["name"]
            for column in inspect(engine).get_columns("market_metric_records")
        }
        assert "data_timing" in metric_columns
        contribution_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "market_contribution_records"
            )
        }
        assert {
            "market_cap_source_provider",
            "classification_source",
            "collected_at",
            "data_timing",
            "calculation_method",
            "data_quality",
            "source_kind",
            "proxy_kind",
        } <= contribution_columns
    engine.dispose()


@pytest.mark.parametrize("http_status", [None, 500])
def test_raw_api_error_cannot_be_persisted_as_available(
    http_status: int | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "truth.db", monkeypatch)
    engine = create_engine(database_url)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                """
                INSERT INTO api_raw_responses (
                    provider,
                    function_name,
                    request_params_hash,
                    received_at,
                    http_status,
                    data_state
                ) VALUES (
                    'audit-test',
                    'minimum-read',
                    '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
                    '2026-07-29T03:00:00+09:00',
                    :http_status,
                    'AVAILABLE'
                )
                """
            ),
            {"http_status": http_status},
        )
    engine.dispose()


@pytest.mark.parametrize(
    ("table_name", "constraint_name"),
    [
        ("dividends", "ck_dividend_available_filing_date"),
        ("dividend_facts", "ck_dividend_fact_available_filing_date"),
        ("audit_opinions", "ck_audit_available_filing_date"),
    ],
)
def test_available_dart_analysis_requires_filing_date(
    table_name: str,
    constraint_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / f"{table_name}.db",
        monkeypatch,
    )
    engine = create_engine(database_url)

    constraint_names = {
        item["name"]
        for item in inspect(engine).get_check_constraints(table_name)
    }

    engine.dispose()
    assert constraint_name in constraint_names


@pytest.mark.parametrize(
    ("table_name", "expected_constraints"),
    [
        (
            "investor_flows",
            {"ck_investor_flow_available_quantity_integral"},
        ),
        (
            "program_trading",
            {"ck_program_available_quantity_integral"},
        ),
        (
            "short_selling",
            {
                "ck_short_available_quantity_valid",
                "ck_short_available_amount_nonnegative",
                "ck_short_available_ratio_range",
            },
        ),
    ],
)
def test_phase5_available_reference_values_have_database_truth_constraints(
    table_name: str,
    expected_constraints: set[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(
        tmp_path / f"{table_name}-truth.db",
        monkeypatch,
    )
    engine = create_engine(database_url)
    actual = {
        item["name"]
        for item in inspect(engine).get_check_constraints(table_name)
    }
    engine.dispose()
    assert expected_constraints <= actual


def test_phase5_audit_marks_legacy_invalid_reference_values_as_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "phase5-legacy-truth.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "p2e5f6a7b8c9")
    engine = create_engine(database_url)
    metadata = {
        "source_provider": "한국투자증권",
        "source_function": "audit fixture",
        "data_state": "AVAILABLE",
        "as_of_at": "2026-07-29T00:00:00+09:00",
        "collected_at": "2026-07-29T18:00:00+09:00",
        "data_timing": "DELAYED",
        "created_at": "2026-07-29T18:00:00+09:00",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO stocks (
                    symbol, name_ko, listing_status, universe_status,
                    quality_state, dart_data_state, source_provider,
                    source_function, data_state, created_at, collected_at,
                    data_timing
                ) VALUES (
                    '000001', 'Phase5Migration', 'LISTED', 'REVIEW_REQUIRED',
                    'REVIEW_REQUIRED', 'NOT_VERIFIED', 'KRX',
                    'audit fixture', 'AVAILABLE',
                    '2026-07-29T18:00:00+09:00',
                    '2026-07-29T18:00:00+09:00', 'NOT_APPLICABLE'
                )
                """
            )
        )
        stock_id = connection.scalar(
            text("SELECT id FROM stocks WHERE symbol='000001'")
        )
        connection.execute(
            text(
                """
                INSERT INTO investor_flows (
                    stock_id, trade_date, investor_type,
                    net_purchase_quantity, source_provider, source_function,
                    data_state, as_of_at, collected_at, data_timing, created_at
                ) VALUES (
                    :stock_id, '2026-07-29', 'FOREIGN', 1.5,
                    :source_provider, :source_function, :data_state,
                    :as_of_at, :collected_at, :data_timing, :created_at
                )
                """
            ),
            {"stock_id": stock_id, **metadata},
        )
        connection.execute(
            text(
                """
                INSERT INTO program_trading (
                    market_code, trade_date, net_purchase_quantity,
                    source_provider, source_function, data_state, as_of_at,
                    collected_at, data_timing, created_at
                ) VALUES (
                    'KOSPI', '2026-07-29', 2.5,
                    :source_provider, :source_function, :data_state, :as_of_at,
                    :collected_at, :data_timing, :created_at
                )
                """
            ),
            metadata,
        )
        connection.execute(
            text(
                """
                INSERT INTO short_selling (
                    stock_id, trade_date, short_quantity, short_ratio,
                    source_provider, source_function, data_state, as_of_at,
                    collected_at, data_timing, created_at
                ) VALUES (
                    :stock_id, '2026-07-29', -1, 101,
                    :source_provider, :source_function, :data_state, :as_of_at,
                    :collected_at, :data_timing, :created_at
                )
                """
            ),
            {"stock_id": stock_id, **metadata},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        for table_name in (
            "investor_flows",
            "program_trading",
            "short_selling",
        ):
            assert connection.scalar(
                text(f"SELECT data_state FROM {table_name}")
            ) == "CONFLICT"
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    UPDATE short_selling
                    SET data_state = 'AVAILABLE', short_quantity = -1
                    """
                )
            )
    engine.dispose()


def test_phase_1b_audit_clears_unverified_assumed_currency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "phase1b-audit.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "e1f4a5b6c7d8")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO stocks (
                    symbol, name_ko, listing_status, universe_status,
                    quality_state, dart_data_state, source_provider,
                    source_function, data_state, created_at, collected_at,
                    data_timing
                ) VALUES (
                    '000001', '통화검증', 'LISTED', 'REVIEW_REQUIRED',
                    'REVIEW_REQUIRED', 'NOT_VERIFIED', 'KRX',
                    '유가증권 종목기본정보', 'AVAILABLE',
                    '2026-07-29T11:00:00+09:00',
                    '2026-07-29T11:00:00+09:00', 'NOT_APPLICABLE'
                )
                """
            )
        )
        stock_id = connection.execute(
            text("SELECT id FROM stocks WHERE symbol='000001'")
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO price_daily (
                    stock_id, trade_date, currency, close_price,
                    adjustment_status, source_provider, source_function,
                    data_state, created_at, as_of_at, collected_at, data_timing
                ) VALUES (
                    :stock_id, '2026-07-29', 'KRW', 10000,
                    'NOT_VERIFIED', 'KRX', '유가증권 일별매매정보',
                    'AVAILABLE', '2026-07-29T18:00:00+09:00',
                    '2026-07-29T00:00:00+09:00',
                    '2026-07-29T18:00:00+09:00', 'PREVIOUS_CLOSE'
                )
                """
            ),
            {"stock_id": stock_id},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT currency FROM price_daily")
        ).scalar_one() is None
    engine.dispose()


def test_phase_3_audit_marks_legacy_metric_timing_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "phase3-legacy-timing.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "k7f0a1b2c3d4")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO market_regime_snapshots (
                    as_of_at, rule_version, input_data_hash, data_state,
                    shock_classification, market_regime, proxy_kind,
                    missing_core_data, explanation, created_at
                ) VALUES (
                    '2026-07-29T18:00:00+09:00', 'phase3-rule-v1',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'MISSING', 'UNCERTAIN', 'UNCERTAIN', 'NOT_AVAILABLE',
                    '[]', 'legacy fixture', '2026-07-29T18:00:00+09:00'
                )
                """
            )
        )
        snapshot_id = connection.execute(
            text("SELECT id FROM market_regime_snapshots")
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO market_metric_records (
                    market_regime_snapshot_id, metric_code, metric_label,
                    state, calculation_method, data_quality, source_kind,
                    proxy_kind, created_at
                ) VALUES (
                    :snapshot_id, 'KOSPI_CURRENT', 'KOSPI 종가', 'MISSING',
                    'legacy', 'MISSING', 'OFFICIAL_API', 'NOT_AVAILABLE',
                    '2026-07-29T18:00:00+09:00'
                )
                """
            ),
            {"snapshot_id": snapshot_id},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT data_timing FROM market_metric_records")
        ).scalar_one() == "UNKNOWN"
    engine.dispose()
