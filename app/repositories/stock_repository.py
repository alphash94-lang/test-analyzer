from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.market import Stock, StockClassification
from app.models.metadata import DataState, DataTiming
from app.models.stock import (
    ClassifiedStock,
    DartCorpCodeItem,
    ListingStatus,
    ProductType,
    ShareClass,
    StockQualityState,
    StockSearchResult,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.utils.dates import restore_database_kst


class StockRepository:
    def __init__(
        self,
        quality_repository: DataQualityRepository | None = None,
    ) -> None:
        self._quality = quality_repository or DataQualityRepository()

    def upsert_krx_records(
        self,
        session: Session,
        records: list[ClassifiedStock],
        *,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> tuple[int, int]:
        if not records:
            return 0, 0

        symbols = {classified.item.symbol for classified in records}
        stocks_by_symbol = {
            stock.symbol: stock
            for stock in session.scalars(
                select(Stock).where(Stock.symbol.in_(symbols))
            ).all()
        }
        review_required = 0
        valid_from = as_of_at.date()
        for classified in records:
            item = classified.item
            stock = stocks_by_symbol.get(item.symbol)
            if stock is None:
                stock = Stock(
                    symbol=item.symbol,
                    name_ko=item.name,
                    source_provider="KRX",
                    source_function="유가증권 종목기본정보",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=collected_at,
                )
                session.add(stock)
                stocks_by_symbol[item.symbol] = stock

            stock.issue_code = item.issue_code
            stock.name_ko = item.name
            stock.abbreviated_name = item.abbreviated_name
            stock.name_en = item.english_name
            stock.market_code = item.market_type_name
            stock.market_name = item.market_type_name
            stock.is_kospi = classified.is_kospi
            stock.security_type = classified.product_type.value
            stock.security_group_name = item.security_group_name
            stock.department_name = item.department_name
            stock.certificate_type_name = item.certificate_type_name
            stock.share_class = classified.share_class.value
            stock.par_value_raw = item.par_value_raw or None
            stock.listed_shares_raw = item.listed_shares_raw or None
            stock.listed_on = item.listed_on
            stock.listing_status = classified.listing_status.value
            stock.universe_status = classified.universe_status.value
            stock.quality_state = classified.quality_state.value
            stock.is_active = True
            stock.source_provider = "KRX"
            stock.source_function = "유가증권 종목기본정보"
            stock.data_state = DataState.AVAILABLE.value
            stock.as_of_at = as_of_at
            stock.collected_at = collected_at
            stock.data_timing = DataTiming.NOT_APPLICABLE.value

        session.flush()
        stock_ids = [stock.id for stock in stocks_by_symbol.values()]
        existing_classifications = {
            (
                row.stock_id,
                row.classification_system,
                row.classification_code,
                row.valid_from,
            ): row
            for row in session.scalars(
                select(StockClassification).where(
                    StockClassification.stock_id.in_(stock_ids),
                    StockClassification.valid_from == valid_from,
                )
            ).all()
            if row.valid_from is not None
        }

        for classified in records:
            item = classified.item
            stock = stocks_by_symbol[item.symbol]
            classifications = {
                "KRX_MARKET_TYPE": item.market_type_name,
                "KRX_SECURITY_GROUP": item.security_group_name,
                "KRX_DEPARTMENT": item.department_name,
                "KRX_CERTIFICATE_TYPE": item.certificate_type_name,
                "NORMALIZED_PRODUCT": classified.product_type.value,
                "NORMALIZED_SHARE_CLASS": classified.share_class.value,
            }
            for system, code in classifications.items():
                if code:
                    self._upsert_classification(
                        session,
                        stock=stock,
                        system=system,
                        code=code,
                        valid_from=valid_from,
                        as_of_at=as_of_at,
                        collected_at=collected_at,
                        existing_rows=existing_classifications,
                    )

            if classified.review_reason:
                review_required += 1
                self._quality.add(
                    session,
                    entity_type="stock",
                    entity_id=item.symbol,
                    provider="KRX",
                    issue_code="REVIEW_REQUIRED_CLASSIFICATION",
                    severity="WARNING",
                    data_state=DataState.NOT_VERIFIED,
                    message=classified.review_reason,
                    context={
                        "security_group_name": item.security_group_name,
                        "certificate_type_name": item.certificate_type_name,
                    },
                )
        return len(records), review_required

    def apply_dart_codes(
        self,
        session: Session,
        records: list[DartCorpCodeItem],
        *,
        collected_at: datetime,
    ) -> int:
        listed_records = [record for record in records if record.stock_code]
        grouped: dict[str, list[DartCorpCodeItem]] = {}
        for record in listed_records:
            grouped.setdefault(record.stock_code or "", []).append(record)

        mapped = 0
        stocks = session.scalars(select(Stock).where(Stock.is_active.is_(True))).all()
        for stock in stocks:
            if stock.security_type != ProductType.STOCK.value:
                continue
            matches = grouped.get(stock.symbol, [])
            if len(matches) == 1:
                match = matches[0]
                stock.dart_corp_code = match.corp_code
                stock.dart_modified_on = match.modify_date
                stock.dart_collected_at = collected_at
                stock.dart_data_state = DataState.AVAILABLE.value
                if stock.quality_state != StockQualityState.REVIEW_REQUIRED.value:
                    stock.quality_state = StockQualityState.VALID.value
                mapped += 1
            elif not matches:
                stock.dart_corp_code = None
                stock.dart_modified_on = None
                stock.dart_collected_at = collected_at
                stock.dart_data_state = DataState.MISSING.value
                stock.quality_state = StockQualityState.MISSING_DART_CODE.value
                self._quality.add(
                    session,
                    entity_type="stock",
                    entity_id=stock.symbol,
                    provider="OpenDART",
                    issue_code="MISSING_DART_CODE",
                    severity="WARNING",
                    data_state=DataState.MISSING,
                    message="OpenDART 고유번호 매핑 결과가 없습니다.",
                )
            else:
                stock.dart_corp_code = None
                stock.dart_modified_on = None
                stock.dart_collected_at = collected_at
                stock.dart_data_state = DataState.CONFLICT.value
                stock.quality_state = StockQualityState.CONFLICT.value
                self._quality.add(
                    session,
                    entity_type="stock",
                    entity_id=stock.symbol,
                    provider="OpenDART",
                    issue_code="DART_CODE_CONFLICT",
                    severity="ERROR",
                    data_state=DataState.CONFLICT,
                    message="하나의 종목코드에 여러 OpenDART 고유번호가 있습니다.",
                    context={"corp_codes": [item.corp_code for item in matches]},
                )
        return mapped

    def upsert_dart_industry(
        self,
        session: Session,
        *,
        stock: Stock,
        industry_code: str,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> None:
        kind = (
            "FINANCIAL"
            if industry_code[:2] in {"64", "65", "66"}
            else "NON_FINANCIAL"
        )
        for system, code in {
            "DART_INDUSTRY_KIND": kind,
            "DART_INDUSTRY": industry_code,
            "DART_PARENT_INDUSTRY": industry_code[:2],
        }.items():
            self._upsert_classification(
                session,
                stock=stock,
                system=system,
                code=code,
                valid_from=as_of_at.date(),
                as_of_at=as_of_at,
                collected_at=collected_at,
                provider="OpenDART",
                function_name="기업개황",
            )

    def upsert_kis_semiconductor_flag(
        self,
        session: Session,
        *,
        stock: Stock,
        flag: str,
        as_of_at: datetime,
        collected_at: datetime,
        existing_rows: dict[
            tuple[int, str, str, date], StockClassification
        ]
        | None = None,
    ) -> None:
        self._upsert_classification(
            session,
            stock=stock,
            system="KIS_SEMICONDUCTOR_FLAG",
            code=flag,
            valid_from=as_of_at.date(),
            as_of_at=as_of_at,
            collected_at=collected_at,
            provider="한국투자증권",
            function_name="KOSPI 종목마스터",
            existing_rows=existing_rows,
        )

    def upsert_kis_industry(
        self,
        session: Session,
        *,
        stock: Stock,
        industry_name: str,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> None:
        self._upsert_classification(
            session,
            stock=stock,
            system="KIS_INDUSTRY_NAME",
            code=industry_name,
            valid_from=as_of_at.date(),
            as_of_at=as_of_at,
            collected_at=collected_at,
            provider="한국투자증권",
            function_name="주식현재가 시세(PER·PBR)",
        )

    def mark_dart_unverified(
        self,
        session: Session,
        data_state: DataState,
    ) -> int:
        rows = session.scalars(
            select(Stock).where(
                Stock.is_active.is_(True),
                Stock.security_type == ProductType.STOCK.value,
            )
        ).all()
        for stock in rows:
            stock.dart_data_state = data_state.value
            if stock.quality_state == StockQualityState.VALID.value:
                stock.quality_state = StockQualityState.REVIEW_REQUIRED.value
        return len(rows)

    def search(
        self,
        session: Session,
        query: str,
        *,
        limit: int = 50,
    ) -> list[StockSearchResult]:
        normalized = query.strip()
        if not normalized:
            return []
        statement = select(Stock).where(Stock.is_active.is_(True))
        if len(normalized) == 6 and normalized.isdigit():
            statement = statement.where(Stock.symbol == normalized)
        else:
            statement = statement.where(
                Stock.name_ko.contains(normalized, autoescape=True)
            )
        rows = session.scalars(statement.order_by(Stock.symbol).limit(limit)).all()
        return [
            StockSearchResult(
                symbol=row.symbol,
                name=row.name_ko,
                is_kospi=row.is_kospi,
                market_name=row.market_name,
                official_product_name=row.security_group_name,
                product_type=ProductType(
                    row.security_type or ProductType.UNKNOWN.value
                ),
                official_share_class_name=row.certificate_type_name,
                share_class=ShareClass(row.share_class or ShareClass.UNKNOWN.value),
                listing_status=ListingStatus(row.listing_status),
                dart_corp_code=row.dart_corp_code,
                dart_modified_on=row.dart_modified_on,
                dart_collected_at=(
                    restore_database_kst(row.dart_collected_at)
                    if row.dart_collected_at is not None
                    else None
                ),
                dart_data_state=DataState(row.dart_data_state),
                source_provider=row.source_provider,
                as_of_at=(
                    restore_database_kst(row.as_of_at)
                    if row.as_of_at is not None
                    else None
                ),
                collected_at=restore_database_kst(row.collected_at),
                quality_state=StockQualityState(row.quality_state),
            )
            for row in rows
        ]

    def count(self, session: Session) -> int:
        value = session.scalar(select(func.count()).select_from(Stock))
        if value is None:
            raise RuntimeError("database COUNT returned no scalar value")
        return value

    @staticmethod
    def _upsert_classification(
        session: Session,
        *,
        stock: Stock,
        system: str,
        code: str,
        valid_from: date,
        as_of_at: datetime,
        collected_at: datetime,
        provider: str = "KRX",
        function_name: str = "유가증권 종목기본정보",
        existing_rows: dict[
            tuple[int, str, str, date], StockClassification
        ]
        | None = None,
    ) -> None:
        key = (stock.id, system, code, valid_from)
        row = (
            existing_rows.get(key)
            if existing_rows is not None
            else session.scalar(
                select(StockClassification).where(
                    StockClassification.stock_id == stock.id,
                    StockClassification.classification_system == system,
                    StockClassification.classification_code == code,
                    StockClassification.valid_from == valid_from,
                )
            )
        )
        if row is None:
            row = StockClassification(
                stock_id=stock.id,
                classification_system=system,
                classification_code=code,
                valid_from=valid_from,
                source_provider=provider,
                source_function=function_name,
                data_state=DataState.AVAILABLE.value,
                collected_at=collected_at,
            )
            session.add(row)
            if existing_rows is not None:
                existing_rows[key] = row
        row.classification_name = code
        row.source_provider = provider
        row.source_function = function_name
        row.as_of_at = as_of_at
        row.collected_at = collected_at
        row.data_timing = DataTiming.NOT_APPLICABLE.value
