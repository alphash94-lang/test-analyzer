from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256

from app.models.metadata import DataState
from app.models.scoring import (
    ComponentState,
    EntityKind,
    FilterState,
    IndustryComparison,
    Phase2Evidence,
    Phase2Result,
    Phase2Rules,
    ScoreComponent,
)
from app.services.confidence_entry_scoring import (
    confidence_components,
    entry_components,
)
from app.services.dividend_scoring import dividend_components
from app.services.financial_scoring import financial_components
from app.services.forced_filter_service import evaluate_forced_filters
from app.services.score_component_common import quantize_score
from app.services.valuation_scoring import valuation_components


def _input_hash(evidence: Phase2Evidence, rules: Phase2Rules) -> str:
    payload = {
        "evidence": evidence.model_dump(mode="json"),
        "rules": rules.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _sum_contributions(components: tuple[ScoreComponent, ...]) -> Decimal:
    return sum(
        (component.contribution or Decimal(0) for component in components),
        start=Decimal(0),
    )


# These are supporting comparisons, not facts that every listed company can
# possess.  A newly initiated dividend, a non-dividend policy, or insufficient
# stored valuation history must not by itself make the whole quality score
# impossible.  Missing items are excluded and the remaining weights are
# normalized, while data confidence continues to reflect reduced coverage.
_SUPPORTING_COMPONENTS = {
    "DIVIDEND_CONTINUITY",
    "DIVIDEND_STABILITY",
    "HISTORICAL_PER",
    "HISTORICAL_PBR",
}
_REQUIRED_FINANCIAL_COMPONENTS = {
    "OPERATING_MARGIN",
    "ROE",
    "DEBT_RATIO",
    "CASH_CONVERSION",
}
_MINIMUM_CORE_WEIGHT_COVERAGE = Decimal("0.60")


def evaluate_phase2(
    evidence: Phase2Evidence,
    rules: Phase2Rules,
) -> Phase2Result:
    filters = evaluate_forced_filters(
        evidence.market,
        evidence.audit,
        evidence.liquidity,
        evidence.corporate_event,
        evidence.financial_risk,
        as_of_date=evidence.as_of_at.date(),
        rules=rules,
    )
    confidence = confidence_components(evidence.confidence, rules)
    data_confidence = quantize_score(_sum_contributions(confidence))
    blocking_filters = tuple(
        item for item in filters if item.is_blocking and item.state != FilterState.PASS
    )
    missing_core = [
        item.code
        for item in blocking_filters
        if item.state
        in {
            FilterState.MISSING,
            FilterState.REVIEW_REQUIRED,
            FilterState.NOT_APPLICABLE,
        }
    ]
    failed_filters = [
        item.code for item in blocking_filters if item.state == FilterState.FAIL
    ]
    core: tuple[ScoreComponent, ...] = ()
    comparisons: tuple[IndustryComparison, ...] = ()
    entry: tuple[ScoreComponent, ...] = ()
    investment_score: Decimal | None = None
    individual_entry_score: Decimal | None = None
    if not blocking_filters:
        entity_kind = (
            evidence.financial_risk.entity_kind
            if evidence.financial_risk is not None
            else EntityKind.UNKNOWN
        )
        valuation, comparisons = valuation_components(
            evidence.valuation,
            rules,
        )
        core = (
            *dividend_components(evidence.dividend, rules),
            *financial_components(
                evidence.financial_quality,
                entity_kind,
                rules,
            ),
            *valuation,
        )
        unavailable_core = [
            item.code
            for item in core
            if item.state != ComponentState.AVAILABLE
            and (
                item.code not in _SUPPORTING_COMPONENTS
                or item.state == ComponentState.NOT_APPLICABLE
            )
        ]
        available_core = tuple(
            item for item in core if item.state == ComponentState.AVAILABLE
        )
        available_weight = sum(
            (item.weight or Decimal(0) for item in available_core),
            start=Decimal(0),
        )
        required_available = _REQUIRED_FINANCIAL_COMPONENTS <= {
            item.code for item in available_core
        }
        missing_core.extend(unavailable_core)
        if (
            not unavailable_core
            and required_available
            and available_weight
            >= rules.core_weight_total * _MINIMUM_CORE_WEIGHT_COVERAGE
        ):
            investment_score = quantize_score(
                _sum_contributions(available_core)
                / available_weight
                * Decimal(100)
            )
        elif not required_available:
            missing_core.extend(
                sorted(
                    _REQUIRED_FINANCIAL_COMPONENTS
                    - {item.code for item in available_core}
                )
            )
        elif available_weight < rules.core_weight_total * _MINIMUM_CORE_WEIGHT_COVERAGE:
            missing_core.append("CORE_DATA_COVERAGE")
        entry = entry_components(evidence.entry)
        if all(component.state == ComponentState.AVAILABLE for component in entry):
            individual_entry_score = quantize_score(
                _sum_contributions(entry) / Decimal(20) * Decimal(100)
            )
        else:
            missing_core.append("ENTRY_INDIVIDUAL")
    components = (*core, *entry, *confidence)
    recommendation_computable = (
        not failed_filters
        and not missing_core
        and investment_score is not None
        and individual_entry_score is not None
        and data_confidence >= rules.confidence_minimum
    )
    if failed_filters:
        explanation = (
            "강제필터 실패는 점수로 상쇄하지 않습니다. 실패 필터: "
            + ", ".join(failed_filters)
        )
        data_state = DataState.NOT_VERIFIED
    elif missing_core:
        explanation = (
            "핵심 데이터가 없어 낮은 점수를 임의로 부여하지 않고 "
            "추천 계산 불가로 처리했습니다: " + ", ".join(dict.fromkeys(missing_core))
        )
        data_state = DataState.MISSING
    elif data_confidence < rules.confidence_minimum:
        explanation = (
            f"Phase 2 핵심 투자매력은 계산됐지만 데이터 신뢰도 "
            f"{data_confidence}점이 기준 {rules.confidence_minimum}점 "
            "미만이라 추천 계산 불가입니다."
        )
        data_state = DataState.NOT_VERIFIED
    else:
        explanation = (
            "강제필터를 모두 통과했고 Phase 2 핵심 투자매력과 개별 종목 "
            "진입 구성요소를 계산했습니다. 시장국면·뉴스·수급을 포함한 "
            "최종 추천은 후속 Phase 범위입니다."
        )
        data_state = DataState.AVAILABLE
    return Phase2Result(
        symbol=evidence.symbol,
        as_of_at=evidence.as_of_at,
        score_version=rules.score_version,
        rule_version=rules.rule_version,
        input_data_hash=_input_hash(evidence, rules),
        filters=filters,
        components=components,
        valuation_comparisons=comparisons,
        investment_score=investment_score,
        entry_score=None,
        individual_entry_score=individual_entry_score,
        data_confidence=data_confidence,
        recommendation_computable=recommendation_computable,
        missing_core_data=tuple(dict.fromkeys(missing_core)),
        explanation=explanation,
        data_state=data_state,
    )
