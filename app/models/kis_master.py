from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class KisKospiMasterItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str
    semiconductor_flag: str

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if len(value) != 6 or not value.isdigit():
            raise ValueError("KIS master symbol must be six digits")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("KIS master name must not be empty")
        return normalized

    @field_validator("semiconductor_flag")
    @classmethod
    def validate_flag(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"Y", "N"}:
            raise ValueError("KIS semiconductor flag must be Y or N")
        return normalized
