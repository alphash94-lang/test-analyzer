from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def cumulative_to_quarters(
    cumulative_values: Sequence[Decimal | None],
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    if len(cumulative_values) != 4:
        raise ValueError("four cumulative quarter values are required")
    q1, half, nine_months, annual = cumulative_values
    return (
        q1,
        None if half is None or q1 is None else half - q1,
        (None if nine_months is None or half is None else nine_months - half),
        (None if annual is None or nine_months is None else annual - nine_months),
    )


def ttm_from_quarters(
    quarter_values: Sequence[Decimal | None],
) -> Decimal | None:
    if len(quarter_values) != 4:
        raise ValueError("four standalone quarter values are required")
    if any(value is None for value in quarter_values):
        return None
    return sum(
        (value for value in quarter_values if value is not None),
        start=Decimal(0),
    )


def ttm_from_annual_and_interim(
    *,
    prior_annual: Decimal | None,
    current_cumulative: Decimal | None,
    prior_cumulative: Decimal | None,
) -> Decimal | None:
    if prior_annual is None or current_cumulative is None or prior_cumulative is None:
        return None
    return prior_annual + current_cumulative - prior_cumulative
