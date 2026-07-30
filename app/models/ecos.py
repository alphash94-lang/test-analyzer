from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EcosObservation(BaseModel):
    """One validated observation returned by ECOS StatisticSearch."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    stat_code: str = Field(alias="STAT_CODE")
    stat_name: str = Field(alias="STAT_NAME")
    item_code: str = Field(alias="ITEM_CODE1")
    item_name: str = Field(alias="ITEM_NAME1")
    unit_name: str = Field(alias="UNIT_NAME")
    observed_on: date = Field(alias="TIME")
    value: Decimal = Field(alias="DATA_VALUE")

    @field_validator("stat_code", "stat_name", "item_code", "item_name", "unit_name")
    @classmethod
    def require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("ECOS text fields must not be empty")
        return normalized

    @field_validator("observed_on", mode="before")
    @classmethod
    def parse_daily_date(cls, value: object) -> date:
        normalized = str(value).strip()
        if len(normalized) != 8 or not normalized.isdigit():
            raise ValueError("ECOS daily TIME must use YYYYMMDD")
        return date(
            int(normalized[:4]),
            int(normalized[4:6]),
            int(normalized[6:8]),
        )
