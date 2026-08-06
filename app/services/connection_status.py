from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.models.quality import ApiRawResponse
from app.db.session import create_db_engine, dispose_db_engine
from app.models.metadata import DataState
from app.models.status import ConnectionState, ConnectionStatusItem
from app.utils.dates import now_kst, restore_database_kst

REQUIRED_TABLES = frozenset(
    {
        "stocks",
        "stock_classifications",
        "market_status",
        "price_daily",
        "index_daily",
        "kis_access_tokens",
        "market_regime_snapshots",
        "market_metric_records",
        "market_contribution_records",
        "financial_statements",
        "financial_accounts",
        "financial_metrics",
        "forced_filter_results",
        "dividends",
        "dividend_facts",
        "audit_opinions",
        "disclosures",
        "api_raw_responses",
        "data_quality_logs",
        "score_snapshots",
        "score_components",
        "valuation_comparisons",
        "recommendations",
        "recommendation_runs",
        "recommendation_reasons",
        "split_buy_plans",
        "portfolio_settings",
        "portfolio_positions",
        "portfolio_allocations",
        "news_articles",
        "event_records",
        "event_watchlist_items",
        "analyst_opinions",
        "earnings_estimates",
        "investor_flows",
        "program_trading",
        "short_selling",
        "backtest_runs",
    }
)


@dataclass(frozen=True)
class ProviderAttempt:
    data_state: str
    received_at: datetime
    http_status: int | None


def _business_elapsed(start: datetime, end: datetime) -> timedelta:
    """Return elapsed time excluding Saturdays and Sundays."""

    if end <= start:
        return timedelta(0)
    elapsed = timedelta(0)
    cursor = start
    while cursor.date() < end.date():
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if cursor.weekday() < 5:
            elapsed += next_midnight - cursor
        cursor = next_midnight
    if cursor.weekday() < 5:
        elapsed += end - cursor
    return elapsed


def _is_stale(
    received_at: datetime,
    checked_at: datetime,
    *,
    freshness_warning_hours: int,
) -> bool:
    return _business_elapsed(received_at, checked_at) > timedelta(
        hours=freshness_warning_hours
    )


def _has_value(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value().strip())


def _credential_status(
    provider: str,
    credentials: Iterable[tuple[str, SecretStr | None]],
    *,
    latest_attempt: ProviderAttempt | None = None,
    freshness_warning_hours: int = 48,
) -> ConnectionStatusItem:
    credential_list = list(credentials)
    missing = [name for name, value in credential_list if not _has_value(value)]
    checked_at = now_kst()
    if missing:
        return ConnectionStatusItem(
            provider=provider,
            state=ConnectionState.NOT_CONFIGURED,
            detail=f"필요 환경변수: {', '.join(missing)}",
            checked_at=checked_at,
        )
    if latest_attempt is not None and (
        latest_attempt.data_state in {"AVAILABLE", "MISSING"}
        and latest_attempt.http_status is not None
        and 200 <= latest_attempt.http_status <= 299
    ):
        received_at = restore_database_kst(latest_attempt.received_at)
        is_stale = _is_stale(
            received_at,
            checked_at,
            freshness_warning_hours=freshness_warning_hours,
        )
        return ConnectionStatusItem(
            provider=provider,
            state=(
                ConnectionState.STALE
                if is_stale
                else ConnectionState.CONNECTED
            ),
            detail=(
                "저장된 원응답에서 인증된 HTTP 2xx 응답을 확인했습니다. "
                + (
                    "최근 조회 조건에는 결과가 없었지만 연결은 정상입니다. "
                    if latest_attempt.data_state == "MISSING"
                    else "사용 가능한 데이터 응답도 확인했습니다. "
                )
                + (
                    f"마지막 성공이 {freshness_warning_hours}시간 "
                    "최신성 경고 기준을 초과했습니다. "
                    if is_stale
                    else ""
                )
                + "마지막 수집: "
                f"{received_at.strftime('%Y-%m-%d %H:%M:%S KST')}"
            ),
            checked_at=checked_at,
            live_check_performed=False,
        )
    if latest_attempt is not None:
        received_at = restore_database_kst(latest_attempt.received_at)
        return ConnectionStatusItem(
            provider=provider,
            state=ConnectionState.FAILED,
            detail=(
                "가장 최근 실제 호출이 사용 가능한 응답을 만들지 못했습니다. "
                f"상태: {latest_attempt.data_state}, "
                f"HTTP: {latest_attempt.http_status or '확인 불가'}, "
                f"수집시각: {received_at.strftime('%Y-%m-%d %H:%M:%S KST')}"
            ),
            checked_at=checked_at,
            live_check_performed=False,
        )
    return ConnectionStatusItem(
        provider=provider,
        state=ConnectionState.NOT_VERIFIED,
        detail="인증정보가 감지됐지만 실제 API 호출은 수행하지 않았습니다.",
        checked_at=checked_at,
    )


def _naver_status(
    settings: Settings,
    *,
    latest_attempt: ProviderAttempt | None = None,
) -> ConnectionStatusItem:
    api_hub_ready = _has_value(settings.ncp_apigw_api_key_id) and _has_value(
        settings.ncp_apigw_api_key
    )
    legacy_ready = _has_value(settings.naver_client_id) and _has_value(
        settings.naver_client_secret
    )
    if api_hub_ready:
        return _credential_status(
            "네이버 뉴스",
            [
                ("NCP_APIGW_API_KEY_ID", settings.ncp_apigw_api_key_id),
                ("NCP_APIGW_API_KEY", settings.ncp_apigw_api_key),
            ],
            latest_attempt=latest_attempt,
            freshness_warning_hours=settings.data_freshness_warning_hours,
        )
    if legacy_ready:
        return ConnectionStatusItem(
            provider="네이버 뉴스",
            state=ConnectionState.NOT_VERIFIED,
            detail="레거시 인증정보가 감지됐습니다. 신규 운영 연동은 API HUB 계약을 우선합니다.",
            checked_at=now_kst(),
        )
    return ConnectionStatusItem(
        provider="네이버 뉴스",
        state=ConnectionState.NOT_CONFIGURED,
        detail="필요 환경변수: NCP_APIGW_API_KEY_ID, NCP_APIGW_API_KEY",
        checked_at=now_kst(),
    )


def _ecos_status(
    settings: Settings,
    *,
    latest_attempt: ProviderAttempt | None = None,
) -> ConnectionStatusItem:
    if _has_value(settings.ecos_api_key):
        return _credential_status(
            "ECOS",
            [("ECOS_API_KEY", settings.ecos_api_key)],
            latest_attempt=latest_attempt,
            freshness_warning_hours=settings.data_freshness_warning_hours,
        )
    if _has_value(settings.bok_api_key):
        return _credential_status(
            "ECOS",
            [("BOK_API_KEY", settings.bok_api_key)],
            latest_attempt=latest_attempt,
            freshness_warning_hours=settings.data_freshness_warning_hours,
        )
    return ConnectionStatusItem(
        provider="ECOS",
        state=ConnectionState.NOT_CONFIGURED,
        detail="필요 환경변수: BOK_API_KEY 또는 ECOS_API_KEY",
        checked_at=now_kst(),
    )


def _database_status(
    settings: Settings,
    *,
    engine: Engine | None = None,
) -> ConnectionStatusItem:
    checked_at = now_kst()
    owns_engine = engine is None
    active_engine = engine or create_db_engine(settings)
    try:
        with active_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            existing_tables = set(inspect(connection).get_table_names())
        missing_tables = REQUIRED_TABLES - existing_tables
    except (SQLAlchemyError, OSError, ValueError) as exc:
        return ConnectionStatusItem(
            provider="데이터베이스",
            state=ConnectionState.FAILED,
            detail=f"연결 실패: {type(exc).__name__}",
            checked_at=checked_at,
            live_check_performed=True,
        )
    finally:
        if owns_engine:
            dispose_db_engine(active_engine)

    if missing_tables:
        return ConnectionStatusItem(
            provider="데이터베이스",
            state=ConnectionState.FAILED,
            detail="DB 연결은 가능하지만 migration 적용이 필요합니다.",
            checked_at=checked_at,
            live_check_performed=True,
        )
    return ConnectionStatusItem(
        provider="데이터베이스",
        state=ConnectionState.CONNECTED,
        detail="연결 및 현재 Phase 필수 테이블을 확인했습니다.",
        checked_at=checked_at,
        live_check_performed=True,
    )


def _public_provider_status(
    provider: str,
    *,
    latest_attempt: ProviderAttempt | None,
    freshness_warning_hours: int,
) -> ConnectionStatusItem:
    checked_at = now_kst()
    if latest_attempt is None:
        return ConnectionStatusItem(
            provider=provider,
            state=ConnectionState.NOT_VERIFIED,
            detail="공식 공개 조회를 아직 실행하지 않았습니다.",
            checked_at=checked_at,
        )
    received_at = restore_database_kst(latest_attempt.received_at)
    if (
        latest_attempt.data_state == DataState.AVAILABLE.value
        and latest_attempt.http_status is not None
        and 200 <= latest_attempt.http_status <= 299
    ):
        stale = _is_stale(
            received_at,
            checked_at,
            freshness_warning_hours=freshness_warning_hours,
        )
        return ConnectionStatusItem(
            provider=provider,
            state=ConnectionState.STALE if stale else ConnectionState.CONNECTED,
            detail=(
                "공식 공개 목록 응답과 정규화를 확인했습니다. 마지막 수집: "
                f"{received_at.strftime('%Y-%m-%d %H:%M:%S KST')}"
            ),
            checked_at=checked_at,
        )
    return ConnectionStatusItem(
        provider=provider,
        state=ConnectionState.FAILED,
        detail=(
            "최근 공식 공개 조회가 실패했습니다. "
            f"상태={latest_attempt.data_state}, HTTP={latest_attempt.http_status}"
        ),
        checked_at=checked_at,
    )


def get_connection_statuses(settings: Settings) -> list[ConnectionStatusItem]:
    """Return truthful configuration states without performing external API calls."""

    engine = create_db_engine(settings)
    try:
        # Both checks share one SQLAlchemy pool. On remote Postgres this avoids
        # paying for two separate TLS/database handshakes on every status load.
        latest_attempts = _latest_raw_provider_attempts(settings, engine=engine)
        database_status = _database_status(settings, engine=engine)
        return [
            _credential_status(
                "KRX",
                [("KRX_API_KEY", settings.krx_api_key)],
                latest_attempt=latest_attempts.get("KRX"),
                freshness_warning_hours=settings.data_freshness_warning_hours,
            ),
            _credential_status(
                "OpenDART",
                [("DART_API_KEY", settings.dart_api_key)],
                latest_attempt=latest_attempts.get("OpenDART"),
                freshness_warning_hours=settings.data_freshness_warning_hours,
            ),
            _credential_status(
                "한국투자증권",
                [
                    ("KIS_APP_KEY", settings.kis_app_key),
                    ("KIS_APP_SECRET", settings.kis_app_secret),
                ],
                latest_attempt=latest_attempts.get("한국투자증권"),
                freshness_warning_hours=settings.data_freshness_warning_hours,
            ),
            _public_provider_status(
                "KIND",
                latest_attempt=latest_attempts.get("KIND"),
                freshness_warning_hours=settings.data_freshness_warning_hours,
            ),
            _naver_status(
                settings,
                latest_attempt=latest_attempts.get("Naver API HUB"),
            ),
            _ecos_status(
                settings,
                latest_attempt=latest_attempts.get("ECOS"),
            ),
            database_status,
        ]
    finally:
        dispose_db_engine(engine)


def _latest_raw_provider_attempts(
    settings: Settings,
    *,
    engine: Engine | None = None,
) -> dict[str, ProviderAttempt]:
    owns_engine = engine is None
    active_engine = engine or create_db_engine(settings)
    try:
        providers = (
            "KRX",
            "OpenDART",
            "Naver API HUB",
            "한국투자증권",
            "ECOS",
            "KIND",
        )
        ranked = (
            select(
                ApiRawResponse.provider.label("provider"),
                ApiRawResponse.data_state.label("data_state"),
                ApiRawResponse.received_at.label("received_at"),
                ApiRawResponse.http_status.label("http_status"),
                func.row_number()
                .over(
                    partition_by=ApiRawResponse.provider,
                    order_by=(
                        ApiRawResponse.received_at.desc(),
                        ApiRawResponse.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(ApiRawResponse.provider.in_(providers))
            .subquery()
        )
        with active_engine.connect() as connection:
            rows = connection.execute(
                select(
                    ranked.c.provider,
                    ranked.c.data_state,
                    ranked.c.received_at,
                    ranked.c.http_status,
                ).where(ranked.c.row_number == 1)
            ).all()
        attempts: dict[str, ProviderAttempt] = {}
        for provider, data_state, received_at, http_status in rows:
            if provider not in attempts:
                attempts[provider] = ProviderAttempt(
                    data_state=data_state,
                    received_at=received_at,
                    http_status=http_status,
                )
        return attempts
    except (SQLAlchemyError, OSError, ValueError):
        return {}
    finally:
        if owns_engine:
            dispose_db_engine(active_engine)
