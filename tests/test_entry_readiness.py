from decimal import Decimal

from app.models.market_analysis import MarketRegime
from app.models.metadata import DataState
from app.services.recommendation_rules import calculate_entry_score


def test_entry_score_combines_phase2_and_available_phase3_inputs() -> None:
    score = calculate_entry_score(
        individual_entry_score=Decimal(50),
        market_state=DataState.AVAILABLE,
        market_regime=MarketRegime.GREEN,
        semiconductor_recovery=True,
        non_semiconductor_breadth=False,
    )

    assert score == Decimal("60.000")


def test_entry_score_is_withheld_when_phase3_is_incomplete() -> None:
    score = calculate_entry_score(
        individual_entry_score=Decimal(50),
        market_state=DataState.MISSING,
        market_regime=MarketRegime.UNCERTAIN,
        semiconductor_recovery=None,
        non_semiconductor_breadth=None,
    )

    assert score is None


def test_uncertain_regime_with_complete_inputs_gets_conservative_score() -> None:
    score = calculate_entry_score(
        individual_entry_score=Decimal(50),
        market_state=DataState.AVAILABLE,
        market_regime=MarketRegime.UNCERTAIN,
        semiconductor_recovery=False,
        non_semiconductor_breadth=False,
    )

    assert score == Decimal("50.000")
