from __future__ import annotations

from app.models.stock import (
    ClassifiedStock,
    KrxStockMasterItem,
    ListingStatus,
    ProductType,
    ShareClass,
    StockQualityState,
    UniverseStatus,
)

_PRODUCT_TOKENS: tuple[tuple[ProductType, tuple[str, ...]], ...] = (
    (ProductType.ETF, ("ETF", "상장지수펀드")),
    (ProductType.ETN, ("ETN", "상장지수증권")),
    (ProductType.ELW, ("ELW", "주식워런트증권")),
    (
        ProductType.SUBSCRIPTION_WARRANT,
        ("신주인수권증권",),
    ),
    (
        ProductType.SUBSCRIPTION_RIGHT,
        ("신주인수권증서",),
    ),
    (ProductType.SPAC, ("기업인수목적회사", "스팩")),
    (ProductType.REIT, ("부동산투자회사", "리츠")),
)


def _product_type(official_value: str) -> ProductType:
    normalized = official_value.strip()
    upper_value = normalized.upper()
    for product_type, tokens in _PRODUCT_TOKENS:
        if any(
            token.upper() == upper_value if token.isascii() else token == normalized
            for token in tokens
        ):
            return product_type
    if normalized in {"주권", "외국주권"}:
        return ProductType.STOCK
    if not normalized:
        return ProductType.UNKNOWN
    return ProductType.OTHER_OFFICIAL


def _share_class(official_value: str) -> ShareClass:
    normalized = official_value.strip()
    if normalized == "보통주":
        return ShareClass.COMMON
    if normalized == "우선주":
        return ShareClass.PREFERRED
    if not normalized:
        return ShareClass.UNKNOWN
    return ShareClass.OTHER


def classify_krx_stock(item: KrxStockMasterItem) -> ClassifiedStock:
    """Classify only official category fields; never infer from the stock name."""

    product_type = _product_type(item.security_group_name)
    share_class = _share_class(item.certificate_type_name)
    is_kospi = (
        True
        if item.market_type_name in {"유가증권시장", "KOSPI"}
        else None
    )

    if is_kospi is not True:
        universe_status = UniverseStatus.REVIEW_REQUIRED
        quality_state = StockQualityState.REVIEW_REQUIRED
        review_reason = "공식 시장구분 값으로 KOSPI 여부를 확정할 수 없습니다."
    elif product_type in {
        ProductType.ETF,
        ProductType.ETN,
        ProductType.ELW,
        ProductType.SPAC,
        ProductType.REIT,
        ProductType.SUBSCRIPTION_WARRANT,
        ProductType.SUBSCRIPTION_RIGHT,
    }:
        universe_status = UniverseStatus.EXCLUDED
        quality_state = StockQualityState.VALID
        review_reason = None
    elif product_type == ProductType.STOCK and share_class == ShareClass.COMMON:
        universe_status = UniverseStatus.REVIEW_REQUIRED
        quality_state = StockQualityState.REVIEW_REQUIRED
        review_reason = (
            "종목기본정보만으로 거래정지·관리종목 상태를 확인할 수 없습니다."
        )
    else:
        universe_status = UniverseStatus.REVIEW_REQUIRED
        quality_state = StockQualityState.REVIEW_REQUIRED
        review_reason = "공식 상품구분 또는 주식종류 값이 자동 확정 규칙에 없습니다."

    return ClassifiedStock(
        item=item,
        is_kospi=is_kospi,
        product_type=product_type,
        share_class=share_class,
        listing_status=ListingStatus.LISTED,
        universe_status=universe_status,
        quality_state=quality_state,
        review_reason=review_reason,
    )
