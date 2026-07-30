from __future__ import annotations

from dataclasses import dataclass

from app.models.events import (
    ClassifiedEvent,
    EventConfidence,
    EventSentiment,
    TextScope,
    is_disclosure_correction_title,
    normalize_disclosure_base_title,
)

EVENT_RULE_VERSION = "phase5-event-rule-v1"
_PRICE_REFLECTION_NOTE = (
    "공시·기사 공개 전후의 가격·거래량 검증을 수행하지 않았으므로 "
    "주가에 이미 반영됐는지는 확정할 수 없습니다."
)


@dataclass(frozen=True)
class EventRule:
    code: str
    event_type: str
    sentiment: EventSentiment
    keywords: tuple[str, ...]


_RULES = (
    EventRule(
        "EMBEZZLEMENT_BREACH",
        "횡령·배임",
        EventSentiment.NEGATIVE,
        ("횡령", "배임"),
    ),
    EventRule(
        "AUDIT_RISK",
        "감사 위험",
        EventSentiment.NEGATIVE,
        (
            "감사의견거절",
            "한정의견",
            "계속기업불확실성",
            "감사보고서미제출",
        ),
    ),
    EventRule(
        "RIGHTS_OFFERING",
        "유상증자",
        EventSentiment.NEGATIVE,
        ("유상증자결정", "유상증자 결정"),
    ),
    EventRule(
        "MEZZANINE_ISSUE",
        "전환사채·신주인수권부사채",
        EventSentiment.NEGATIVE,
        (
            "전환사채권발행결정",
            "전환사채 발행",
            "신주인수권부사채권발행결정",
            "신주인수권부사채 발행",
        ),
    ),
    EventRule(
        "DIVIDEND_CUT",
        "배당 축소·중단",
        EventSentiment.NEGATIVE,
        ("배당중단", "무배당", "배당 축소", "배당감소"),
    ),
    EventRule(
        "SANCTION",
        "제재·거래정지",
        EventSentiment.NEGATIVE,
        ("거래정지", "불성실공시", "제재", "상장적격성"),
    ),
    EventRule(
        "LITIGATION",
        "소송",
        EventSentiment.NEGATIVE,
        ("소송등의제기", "소송 등의 제기", "중재신청"),
    ),
    EventRule(
        "IMPAIRMENT",
        "손상차손",
        EventSentiment.NEGATIVE,
        ("손상차손", "자산손상"),
    ),
    EventRule(
        "OPERATING_LOSS",
        "영업손실·실적 하향",
        EventSentiment.NEGATIVE,
        ("영업손실", "적자전환", "전망 하향", "가이던스 하향"),
    ),
    EventRule(
        "TREASURY_SHARE_CANCEL",
        "자기주식 소각",
        EventSentiment.POSITIVE,
        ("자기주식소각결정", "자기주식 소각"),
    ),
    EventRule(
        "TREASURY_SHARE_BUYBACK",
        "자기주식 취득",
        EventSentiment.POSITIVE,
        ("자기주식취득결정", "자기주식 취득"),
    ),
    EventRule(
        "LARGE_CONTRACT",
        "대규모 수주·공급계약",
        EventSentiment.POSITIVE,
        ("단일판매ㆍ공급계약체결", "단일판매·공급계약", "대규모 수주"),
    ),
    EventRule(
        "VALUE_UP",
        "기업가치 제고",
        EventSentiment.POSITIVE,
        ("기업가치제고계획", "기업가치 제고 계획", "밸류업"),
    ),
    EventRule(
        "GUIDANCE_UP",
        "실적 전망 상향",
        EventSentiment.POSITIVE,
        ("전망 상향", "가이던스 상향"),
    ),
    EventRule(
        "DEBT_REDUCTION",
        "부채 감소",
        EventSentiment.POSITIVE,
        ("차입금 상환", "부채 감소", "재무구조 개선"),
    ),
    EventRule(
        "DIVIDEND_DECISION",
        "배당 결정",
        EventSentiment.NEUTRAL,
        ("현금ㆍ현물배당결정", "현금·현물배당결정", "배당결정"),
    ),
    EventRule(
        "AUDIT_REPORT",
        "감사보고서",
        EventSentiment.NEUTRAL,
        ("감사보고서제출", "감사보고서 제출"),
    ),
    EventRule(
        "CONTROLLING_SHAREHOLDER_CHANGE",
        "최대주주 변경",
        EventSentiment.NEUTRAL,
        ("최대주주변경", "최대주주 변경"),
    ),
    EventRule(
        "BUSINESS_REORGANIZATION",
        "기업 구조 변경",
        EventSentiment.NEUTRAL,
        ("합병결정", "회사분할결정", "영업양수도결정"),
    ),
)


def disclosure_base_title(title: str) -> str:
    return normalize_disclosure_base_title(title)


def classify_disclosure(
    title: str,
    *,
    rule_version: str = EVENT_RULE_VERSION,
) -> ClassifiedEvent | None:
    is_correction = is_disclosure_correction_title(title)
    normalized = disclosure_base_title(title)
    for rule in _RULES:
        matched = next(
            (keyword for keyword in rule.keywords if keyword.replace(" ", "") in normalized),
            None,
        )
        if matched is not None:
            if is_correction:
                return ClassifiedEvent(
                    event_type=f"정정공시 · {rule.event_type}",
                    sentiment=EventSentiment.UNCLASSIFIED,
                    confidence=EventConfidence.LOW,
                    rationale=(
                        "정정공시는 제목만으로 원공시에서 변경된 내용과 "
                        "방향을 확인할 수 없어 긍정·부정을 확정하지 않았습니다."
                    ),
                    matched_rule=(
                        f"CORRECTION_REQUIRES_ORIGINAL_REVIEW:{rule.code}"
                    ),
                    text_scope=TextScope.DISCLOSURE_TITLE_ONLY,
                    used_text=title.strip(),
                    price_reflection_note=_PRICE_REFLECTION_NOTE,
                    rule_version=rule_version,
                )
            return _classified(
                rule,
                matched,
                TextScope.DISCLOSURE_TITLE_ONLY,
                title.strip(),
                EventConfidence.HIGH,
                rule_version,
            )
    return None


def classify_news(
    title: str,
    summary: str,
    *,
    rule_version: str = EVENT_RULE_VERSION,
) -> ClassifiedEvent:
    used_text = f"제목: {title.strip()}\n제공 요약: {summary.strip()}"
    normalized = f"{title} {summary}".replace(" ", "")
    for rule in _RULES:
        matched = next(
            (keyword for keyword in rule.keywords if keyword.replace(" ", "") in normalized),
            None,
        )
        if matched is not None:
            return _classified(
                rule,
                matched,
                TextScope.TITLE_AND_PROVIDED_SUMMARY,
                used_text,
                EventConfidence.MEDIUM,
                rule_version,
            )
    return ClassifiedEvent(
        event_type="일반 뉴스",
        sentiment=EventSentiment.UNCLASSIFIED,
        confidence=EventConfidence.LOW,
        rationale=(
            "구조화 이벤트 규칙과 일치하는 표현이 없어 감성을 확정하지 않았습니다."
        ),
        matched_rule="NO_STRUCTURED_RULE_MATCH",
        text_scope=TextScope.TITLE_AND_PROVIDED_SUMMARY,
        used_text=used_text,
        price_reflection_note=_PRICE_REFLECTION_NOTE,
        rule_version=rule_version,
    )


def _classified(
    rule: EventRule,
    matched_keyword: str,
    text_scope: TextScope,
    used_text: str,
    confidence: EventConfidence,
    rule_version: str,
) -> ClassifiedEvent:
    return ClassifiedEvent(
        event_type=rule.event_type,
        sentiment=rule.sentiment,
        confidence=confidence,
        rationale=(
            f"구조화 규칙 {rule.code}의 표현 "
            f"'{matched_keyword}'이 제공 텍스트에서 확인됐습니다."
        ),
        matched_rule=rule.code,
        text_scope=text_scope,
        used_text=used_text,
        price_reflection_note=_PRICE_REFLECTION_NOTE,
        rule_version=rule_version,
    )
