from __future__ import annotations

from decimal import Decimal

from app.models.financial import parse_dart_decimal

_DPS_LABELS = {
    "주당 현금배당금(원)",
    "주당 현금배당금 (원)",
}


def parse_confirmed_dividend_fact(
    *,
    label: str,
    raw_value: str | None,
) -> tuple[Decimal, str] | None:
    if label.strip() not in _DPS_LABELS:
        return None
    value = parse_dart_decimal(raw_value)
    if value is None or value < 0:
        return None
    return value, "KRW"
