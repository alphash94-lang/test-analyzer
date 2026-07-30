from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.metadata import DataState
from app.utils.dates import ensure_kst


class ProductType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    ETN = "ETN"
    ELW = "ELW"
    SPAC = "SPAC"
    REIT = "REIT"
    SUBSCRIPTION_WARRANT = "SUBSCRIPTION_WARRANT"
    SUBSCRIPTION_RIGHT = "SUBSCRIPTION_RIGHT"
    OTHER_OFFICIAL = "OTHER_OFFICIAL"
    UNKNOWN = "UNKNOWN"


class ShareClass(StrEnum):
    COMMON = "COMMON"
    PREFERRED = "PREFERRED"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ListingStatus(StrEnum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class UniverseStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class StockQualityState(StrEnum):
    VALID = "VALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MISSING_DART_CODE = "MISSING_DART_CODE"
    CONFLICT = "CONFLICT"


class KrxStockMasterItem(BaseModel):
    """Fields confirmed in the official KRX stock-master contract."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    issue_code: str = Field(alias="ISU_CD")
    symbol: str = Field(alias="ISU_SRT_CD")
    name: str = Field(alias="ISU_NM")
    abbreviated_name: str = Field(alias="ISU_ABBRV")
    english_name: str = Field(alias="ISU_ENG_NM")
    listed_on_raw: str = Field(alias="LIST_DD")
    market_type_name: str = Field(alias="MKT_TP_NM")
    security_group_name: str = Field(alias="SECUGRP_NM")
    department_name: str = Field(alias="SECT_TP_NM")
    certificate_type_name: str = Field(alias="KIND_STKCERT_TP_NM")
    par_value_raw: str = Field(alias="PARVAL")
    listed_shares_raw: str = Field(alias="LIST_SHRS")

    @field_validator("symbol")
    @classmethod
    def require_six_digit_symbol(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("KRX stock symbol must contain exactly six digits")
        return normalized

    @field_validator(
        "issue_code",
        "name",
        "abbreviated_name",
        "english_name",
        "listed_on_raw",
        "market_type_name",
        "security_group_name",
        "department_name",
        "certificate_type_name",
        "par_value_raw",
        "listed_shares_raw",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("KRX official field must not be null")
        return str(value).strip()

    @field_validator(
        "issue_code",
        "name",
        "listed_on_raw",
        "market_type_name",
        "security_group_name",
    )
    @classmethod
    def require_critical_text(cls, value: str) -> str:
        if not value:
            raise ValueError("required KRX official field must not be empty")
        return value

    @field_validator("listed_on_raw")
    @classmethod
    def require_listing_date(cls, value: str) -> str:
        normalized = value.replace("-", "")
        if len(normalized) != 8 or not normalized.isdigit():
            raise ValueError("KRX LIST_DD must use YYYYMMDD")
        try:
            date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
        except ValueError as exc:
            raise ValueError("KRX LIST_DD is not a valid calendar date") from exc
        return value

    @property
    def listed_on(self) -> date:
        value = self.listed_on_raw.replace("-", "")
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


class DartCorpCodeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corp_code: str
    corp_name: str
    corp_eng_name: str
    stock_code: str | None
    modify_date: date

    @field_validator("corp_code")
    @classmethod
    def require_eight_digit_corp_code(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 8 or not normalized.isdigit():
            raise ValueError("OpenDART corp_code must contain exactly eight digits")
        return normalized

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("OpenDART stock_code must contain exactly six digits")
        return normalized

    @field_validator("corp_name")
    @classmethod
    def require_corp_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("OpenDART corp_name must not be empty")
        return normalized


class ClassifiedStock(BaseModel):
    item: KrxStockMasterItem
    is_kospi: bool | None
    product_type: ProductType
    share_class: ShareClass
    listing_status: ListingStatus
    universe_status: UniverseStatus
    quality_state: StockQualityState
    review_reason: str | None = None


class StockSearchResult(BaseModel):
    symbol: str
    name: str
    is_kospi: bool | None
    market_name: str | None
    official_product_name: str | None
    product_type: ProductType
    official_share_class_name: str | None
    share_class: ShareClass
    listing_status: ListingStatus
    dart_corp_code: str | None
    dart_modified_on: date | None
    dart_collected_at: datetime | None
    dart_data_state: DataState
    source_provider: str
    as_of_at: datetime | None
    collected_at: datetime
    quality_state: StockQualityState

    @field_validator("as_of_at", "collected_at", "dart_collected_at")
    @classmethod
    def require_aware_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_kst(value) if value is not None else None


class UniverseRefreshSummary(BaseModel):
    state: str
    started_at: datetime
    finished_at: datetime
    as_of_date: date
    krx_received: int = 0
    stocks_upserted: int = 0
    dart_received: int = 0
    dart_mapped: int = 0
    review_required: int = 0
    errors: tuple[str, ...] = ()
