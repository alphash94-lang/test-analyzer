from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.disclosure import Disclosure
from app.db.models.event import (
    AnalystOpinion,
    EarningsEstimate,
    EventRecord,
    InvestorFlow,
    NewsArticle,
    ProgramTrading,
    ShortSelling,
)
from app.db.models.market import Stock
from app.models.events import (
    AnalystOpinionView,
    ClassifiedEvent,
    CorrectionLinkState,
    EarningsEstimateView,
    EventConfidence,
    EventSentiment,
    EventView,
    InvestorFlowView,
    KisAnalystOpinionItem,
    KisInvestorFlowItem,
    KisProgramTradingItem,
    KisShortSellingItem,
    NaverNewsItem,
    ProgramTradingView,
    ShortSellingView,
    TextScope,
)
from app.models.metadata import DataState, DataTiming
from app.services.event_rules import classify_disclosure, classify_news
from app.utils.dates import restore_database_kst

_TITLE_TOKEN = re.compile(r"[^0-9a-z가-힣]+")
_TRACKING_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "nclick",
        "sm",
        "where",
    }
)


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=False)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in _TRACKING_KEYS
        )
    )
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            query,
            "",
        )
    )


def normalize_title(value: str) -> str:
    return _TITLE_TOKEN.sub("", value.casefold())


class EventRepository:
    def __init__(
        self,
        *,
        title_similarity_threshold: float,
        rule_version: str = "phase5-event-rule-v1",
    ) -> None:
        if not 0.5 <= title_similarity_threshold <= 1:
            raise ValueError("title similarity threshold must be between 0.5 and 1")
        self._title_similarity_threshold = title_similarity_threshold
        self._rule_version = rule_version

    def upsert_news(
        self,
        session: Session,
        *,
        stock: Stock,
        query: str,
        items: tuple[NaverNewsItem, ...],
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> tuple[int, int]:
        candidates = list(
            session.scalars(
                select(NewsArticle).where(NewsArticle.stock_id == stock.id)
            ).all()
        )
        stored = 0
        duplicate = 0
        for item in items:
            original_url = str(item.original_url) if item.original_url else None
            provider_url = str(item.provider_url)
            canonical_url = canonicalize_url(original_url or provider_url)
            normalized_title = normalize_title(item.title)
            content_hash = sha256(
                f"{normalized_title}\n{item.summary}".encode()
            ).hexdigest()
            if self._is_duplicate(
                candidates,
                canonical_url=canonical_url,
                content_hash=content_hash,
                normalized_title=normalized_title,
                published_at=item.published_at,
            ):
                duplicate += 1
                continue
            row = NewsArticle(
                stock_id=stock.id,
                raw_response_id=raw_response_id,
                query=query,
                title=item.title,
                summary=item.summary,
                publisher=None,
                original_url=original_url,
                provider_url=provider_url,
                canonical_url=canonical_url,
                normalized_title=normalized_title,
                content_hash=content_hash,
                published_at=item.published_at,
                used_text_scope=item.text_scope.value,
                source_provider="Naver API HUB",
                source_function="네이버 뉴스 검색 API",
                data_state=DataState.AVAILABLE.value,
                as_of_at=item.published_at,
                collected_at=collected_at,
                data_timing=DataTiming.DELAYED.value,
            )
            session.add(row)
            candidates.append(row)
            classified = classify_news(
                item.title,
                item.summary,
                rule_version=self._rule_version,
            )
            self._upsert_event(
                session,
                stock_id=stock.id,
                raw_response_id=raw_response_id,
                source_provider="Naver API HUB",
                source_kind="NEWS",
                source_record_key=content_hash,
                title=item.title,
                event_date=None,
                published_at=item.published_at,
                collected_at=collected_at,
                source_url=original_url or provider_url,
                classified=classified,
                is_correction=False,
                original_source_key=None,
                correction_link_state=CorrectionLinkState.NOT_APPLICABLE,
            )
            stored += 1
        session.flush()
        return stored, duplicate

    def upsert_disclosure_events(
        self,
        session: Session,
        *,
        stock_id: int,
        disclosures: tuple[Disclosure, ...],
    ) -> int:
        stored = 0
        for disclosure in disclosures:
            classified = classify_disclosure(
                disclosure.report_name,
                rule_version=self._rule_version,
            )
            if classified is None:
                continue
            correction_state = CorrectionLinkState(
                disclosure.correction_link_state
            )
            published_at = datetime.combine(
                disclosure.receipt_date,
                time.min,
                tzinfo=ZoneInfo("Asia/Seoul"),
            )
            created = self._upsert_event(
                session,
                stock_id=stock_id,
                raw_response_id=disclosure.raw_response_id,
                source_provider="OpenDART",
                source_kind="DISCLOSURE",
                source_record_key=disclosure.receipt_no,
                title=disclosure.report_name,
                event_date=None,
                published_at=published_at,
                collected_at=restore_database_kst(disclosure.collected_at),
                source_url=disclosure.source_url,
                classified=classified,
                is_correction=disclosure.is_correction,
                original_source_key=disclosure.original_receipt_no,
                correction_link_state=correction_state,
            )
            stored += int(created)
        session.flush()
        return stored

    @staticmethod
    def upsert_analyst_opinions(
        session: Session,
        *,
        stock: Stock,
        items: list[KisAnalystOpinionItem],
        raw_response_id: int | None,
        collected_at: datetime,
        source_url: str,
    ) -> int:
        stored = 0
        for item in items:
            row = session.scalar(
                select(AnalystOpinion).where(
                    AnalystOpinion.stock_id == stock.id,
                    AnalystOpinion.source_provider == "한국투자증권",
                    AnalystOpinion.broker == "한국투자증권",
                    AnalystOpinion.published_date == item.published_date,
                )
            )
            if row is None:
                row = AnalystOpinion(
                    stock_id=stock.id,
                    broker="한국투자증권",
                    published_date=item.published_date,
                )
                session.add(row)
            row.raw_response_id = raw_response_id
            row.opinion = item.opinion
            row.target_price = item.target_price
            row.currency = item.currency
            row.source_url = source_url
            row.is_estimate = True
            row.source_provider = "한국투자증권"
            row.source_function = "국내주식 종목투자의견"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = datetime.combine(
                item.published_date,
                time.min,
                tzinfo=ZoneInfo("Asia/Seoul"),
            )
            row.collected_at = collected_at
            row.data_timing = DataTiming.DELAYED.value
            stored += 1
        session.flush()
        return stored

    @staticmethod
    def upsert_investor_flows(
        session: Session,
        *,
        stock: Stock,
        items: list[KisInvestorFlowItem],
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in items:
            values = (
                ("FOREIGN", item.foreign_net_quantity),
                ("INSTITUTION", item.institution_net_quantity),
                ("INDIVIDUAL", item.individual_net_quantity),
            )
            for investor_type, quantity in values:
                if quantity is None:
                    continue
                row = session.scalar(
                    select(InvestorFlow).where(
                        InvestorFlow.stock_id == stock.id,
                        InvestorFlow.trade_date == item.trade_date,
                        InvestorFlow.source_provider == "한국투자증권",
                        InvestorFlow.investor_type == investor_type,
                    )
                )
                if row is None:
                    row = InvestorFlow(
                        stock_id=stock.id,
                        trade_date=item.trade_date,
                        investor_type=investor_type,
                    )
                    session.add(row)
                row.raw_response_id = raw_response_id
                row.net_purchase_quantity = quantity
                row.net_purchase_amount = None
                row.currency = None
                row.unit = None
                row.source_provider = "한국투자증권"
                row.source_function = "종목별 투자자매매동향(일별)"
                row.data_state = DataState.AVAILABLE.value
                row.as_of_at = datetime.combine(
                    item.trade_date,
                    time.min,
                    tzinfo=ZoneInfo("Asia/Seoul"),
                )
                row.collected_at = collected_at
                row.data_timing = DataTiming.DELAYED.value
                stored += 1
        session.flush()
        return stored

    @staticmethod
    def upsert_program_trading(
        session: Session,
        *,
        items: list[KisProgramTradingItem],
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in items:
            row = session.scalar(
                select(ProgramTrading).where(
                    ProgramTrading.market_code == "KOSPI",
                    ProgramTrading.trade_date == item.trade_date,
                    ProgramTrading.source_provider == "한국투자증권",
                )
            )
            if row is None:
                row = ProgramTrading(
                    market_code="KOSPI",
                    trade_date=item.trade_date,
                )
                session.add(row)
            row.raw_response_id = raw_response_id
            row.net_purchase_quantity = item.whole_entrusted_net_quantity
            row.net_purchase_amount = None
            row.currency = None
            row.unit = None
            row.source_provider = "한국투자증권"
            row.source_function = "프로그램매매 종합현황(일별)"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = datetime.combine(
                item.trade_date,
                time.min,
                tzinfo=ZoneInfo("Asia/Seoul"),
            )
            row.collected_at = collected_at
            row.data_timing = DataTiming.DELAYED.value
            stored += 1
        session.flush()
        return stored

    @staticmethod
    def upsert_short_selling(
        session: Session,
        *,
        stock: Stock,
        items: list[KisShortSellingItem],
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in items:
            row = session.scalar(
                select(ShortSelling).where(
                    ShortSelling.stock_id == stock.id,
                    ShortSelling.trade_date == item.trade_date,
                    ShortSelling.source_provider == "한국투자증권",
                )
            )
            if row is None:
                row = ShortSelling(
                    stock_id=stock.id,
                    trade_date=item.trade_date,
                )
                session.add(row)
            row.raw_response_id = raw_response_id
            row.short_quantity = item.short_quantity
            row.short_amount = item.short_amount
            row.short_ratio = item.short_ratio_percent
            row.currency = None
            row.unit = None
            row.source_provider = "한국투자증권"
            row.source_function = "국내주식 공매도 일별추이"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = datetime.combine(
                item.trade_date,
                time.min,
                tzinfo=ZoneInfo("Asia/Seoul"),
            )
            row.collected_at = collected_at
            row.data_timing = DataTiming.DELAYED.value
            stored += 1
        session.flush()
        return stored

    def views(
        self,
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[EventView, ...]:
        criteria = [
            EventRecord.stock_id == stock_id,
            EventRecord.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(
                EventRecord.published_at < self._exclusive_date_end(as_of_date)
            )
        rows = session.scalars(
            select(EventRecord)
            .where(*criteria)
            .order_by(
                EventRecord.published_at.desc(),
                EventRecord.id.desc(),
            )
        ).all()
        return tuple(
            EventView(
                title=row.title,
                event_type=row.event_type,
                event_date=row.event_date,
                published_at=restore_database_kst(row.published_at),
                source_provider=row.source_provider,
                source_kind=row.source_kind,
                source_url=row.source_url,
                sentiment=EventSentiment(row.sentiment),
                confidence=EventConfidence(row.confidence),
                rationale=row.rationale,
                used_text_scope=TextScope(row.used_text_scope),
                price_reflection_note=row.price_reflection_note,
                is_correction=row.is_correction,
                original_source_key=row.original_source_key,
                correction_link_state=CorrectionLinkState(
                    row.correction_link_state
                ),
                collected_at=restore_database_kst(row.collected_at),
                data_state=DataState(row.data_state),
            )
            for row in rows
        )

    @staticmethod
    def analyst_views(
        session: Session,
        stock_id: int,
        *,
        since_date: date,
        as_of_date: date | None = None,
    ) -> tuple[AnalystOpinionView, ...]:
        criteria = [
            AnalystOpinion.stock_id == stock_id,
            AnalystOpinion.published_date >= since_date,
            AnalystOpinion.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(AnalystOpinion.published_date <= as_of_date)
        rows = session.scalars(
            select(AnalystOpinion)
            .where(*criteria)
            .order_by(AnalystOpinion.published_date.desc())
        ).all()
        latest_by_broker: dict[str, AnalystOpinion] = {}
        for row in rows:
            latest_by_broker.setdefault(row.broker, row)
        return tuple(
            AnalystOpinionView(
                provider=row.source_provider,
                broker=row.broker,
                opinion=row.opinion,
                target_price=row.target_price,
                currency=row.currency,
                published_date=row.published_date,
                source_url=row.source_url,
                is_estimate=row.is_estimate,
            )
            for row in latest_by_broker.values()
        )

    @staticmethod
    def estimate_views(
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[EarningsEstimateView, ...]:
        criteria = [
            EarningsEstimate.stock_id == stock_id,
            EarningsEstimate.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(EarningsEstimate.published_date <= as_of_date)
        rows = session.scalars(
            select(EarningsEstimate)
            .where(*criteria)
            .order_by(EarningsEstimate.published_date.desc())
        ).all()
        return tuple(
            EarningsEstimateView(
                provider=row.source_provider,
                broker=row.broker,
                metric_code=row.metric_code,
                fiscal_period=row.fiscal_period,
                estimate_value=row.estimate_value,
                unit=row.unit,
                currency=row.currency,
                published_date=row.published_date,
                source_url=row.source_url,
                is_estimate=row.is_estimate,
            )
            for row in rows
        )

    @staticmethod
    def flow_views(
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[InvestorFlowView, ...]:
        criteria = [
            InvestorFlow.stock_id == stock_id,
            InvestorFlow.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(InvestorFlow.trade_date <= as_of_date)
        rows = session.scalars(
            select(InvestorFlow)
            .where(*criteria)
            .order_by(InvestorFlow.trade_date.desc(), InvestorFlow.investor_type)
        ).all()
        return tuple(
            InvestorFlowView(
                provider=row.source_provider,
                trade_date=row.trade_date,
                investor_type=row.investor_type,
                net_purchase_quantity=row.net_purchase_quantity,
                net_purchase_amount=row.net_purchase_amount,
                currency=row.currency,
                unit=row.unit,
            )
            for row in rows
        )

    @staticmethod
    def short_views(
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[ShortSellingView, ...]:
        criteria = [
            ShortSelling.stock_id == stock_id,
            ShortSelling.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(ShortSelling.trade_date <= as_of_date)
        rows = session.scalars(
            select(ShortSelling)
            .where(*criteria)
            .order_by(ShortSelling.trade_date.desc())
        ).all()
        return tuple(
            ShortSellingView(
                provider=row.source_provider,
                trade_date=row.trade_date,
                short_quantity=row.short_quantity,
                short_amount=row.short_amount,
                short_ratio_percent=row.short_ratio,
                currency=row.currency,
                unit=row.unit,
            )
            for row in rows
        )

    @staticmethod
    def program_views(
        session: Session,
        *,
        since_date: date,
        as_of_date: date | None = None,
    ) -> tuple[ProgramTradingView, ...]:
        criteria = [
            ProgramTrading.market_code == "KOSPI",
            ProgramTrading.trade_date >= since_date,
            ProgramTrading.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(ProgramTrading.trade_date <= as_of_date)
        rows = session.scalars(
            select(ProgramTrading)
            .where(*criteria)
            .order_by(ProgramTrading.trade_date.desc())
        ).all()
        return tuple(
            ProgramTradingView(
                provider=row.source_provider,
                market_code=row.market_code,
                trade_date=row.trade_date,
                net_purchase_quantity=row.net_purchase_quantity,
                net_purchase_amount=row.net_purchase_amount,
                currency=row.currency,
                unit=row.unit,
                provider_field="whol_entm_ntby_qty",
            )
            for row in rows
        )

    @staticmethod
    def _exclusive_date_end(as_of_date: date) -> datetime:
        return datetime.combine(
            as_of_date + timedelta(days=1),
            time.min,
            tzinfo=ZoneInfo("Asia/Seoul"),
        )

    def _upsert_event(
        self,
        session: Session,
        *,
        stock_id: int,
        raw_response_id: int | None,
        source_provider: str,
        source_kind: str,
        source_record_key: str,
        title: str,
        event_date: date | None,
        published_at: datetime,
        collected_at: datetime,
        source_url: str | None,
        classified: ClassifiedEvent,
        is_correction: bool,
        original_source_key: str | None,
        correction_link_state: CorrectionLinkState,
    ) -> bool:
        rule_version = classified.rule_version
        row = session.scalar(
            select(EventRecord).where(
                EventRecord.stock_id == stock_id,
                EventRecord.source_provider == source_provider,
                EventRecord.source_record_key == source_record_key,
                EventRecord.rule_version == rule_version,
            )
        )
        created = row is None
        if row is None:
            row = EventRecord(
                source_provider=source_provider,
                source_record_key=source_record_key,
                rule_version=rule_version,
            )
            session.add(row)
        row.stock_id = stock_id
        row.raw_response_id = raw_response_id
        row.source_kind = source_kind
        row.title = title
        row.event_type = classified.event_type
        row.event_date = event_date
        row.published_at = published_at
        row.collected_at = collected_at
        row.source_url = source_url
        row.sentiment = classified.sentiment.value
        row.confidence = classified.confidence.value
        row.rationale = classified.rationale
        row.matched_rule = classified.matched_rule
        row.used_text_scope = classified.text_scope.value
        row.used_text = classified.used_text
        row.price_reflection_note = classified.price_reflection_note
        row.data_state = DataState.AVAILABLE.value
        row.is_correction = is_correction
        row.original_source_key = original_source_key
        row.correction_link_state = correction_link_state.value
        return created

    def _is_duplicate(
        self,
        candidates: list[NewsArticle],
        *,
        canonical_url: str,
        content_hash: str,
        normalized_title: str,
        published_at: datetime,
    ) -> bool:
        for row in candidates:
            if row.canonical_url == canonical_url or row.content_hash == content_hash:
                return True
            row_published = restore_database_kst(row.published_at)
            if abs((row_published.date() - published_at.date()).days) > 2:
                continue
            similarity = SequenceMatcher(
                None,
                row.normalized_title,
                normalized_title,
            ).ratio()
            if similarity >= self._title_similarity_threshold:
                return True
        return False
