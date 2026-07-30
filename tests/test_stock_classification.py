from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.stock import (
    KrxStockMasterItem,
    ProductType,
    ShareClass,
    UniverseStatus,
)
from app.services.stock_classification import classify_krx_stock


def minimum_item(
    *,
    name: str = "분류검증",
    security_group: str = "주권",
    certificate_type: str = "보통주",
) -> KrxStockMasterItem:
    return KrxStockMasterItem.model_validate(
        {
            "ISU_CD": "KR7000000000",
            "ISU_SRT_CD": "000001",
            "ISU_NM": name,
            "ISU_ABBRV": name,
            "ISU_ENG_NM": "Classification Check",
            "LIST_DD": "20260729",
            "MKT_TP_NM": "유가증권시장",
            "SECUGRP_NM": security_group,
            "SECT_TP_NM": "",
            "KIND_STKCERT_TP_NM": certificate_type,
            "PARVAL": "",
            "LIST_SHRS": "",
        }
    )


def test_official_common_stock_still_requires_market_status_review() -> None:
    result = classify_krx_stock(minimum_item())

    assert result.product_type == ProductType.STOCK
    assert result.share_class == ShareClass.COMMON
    assert result.universe_status == UniverseStatus.REVIEW_REQUIRED


def test_official_etf_category_is_excluded() -> None:
    result = classify_krx_stock(
        minimum_item(security_group="ETF", certificate_type="")
    )

    assert result.product_type == ProductType.ETF
    assert result.universe_status == UniverseStatus.EXCLUDED


@pytest.mark.parametrize(
    ("official_value", "expected"),
    [
        ("ETN", ProductType.ETN),
        ("ELW", ProductType.ELW),
        ("기업인수목적회사", ProductType.SPAC),
        ("부동산투자회사", ProductType.REIT),
        ("신주인수권증권", ProductType.SUBSCRIPTION_WARRANT),
        ("신주인수권증서", ProductType.SUBSCRIPTION_RIGHT),
    ],
)
def test_official_non_common_products_are_distinguished(
    official_value: str,
    expected: ProductType,
) -> None:
    result = classify_krx_stock(
        minimum_item(
            security_group=official_value,
            certificate_type="",
        )
    )

    assert result.product_type == expected
    assert result.universe_status == UniverseStatus.EXCLUDED


def test_official_preferred_share_is_not_common() -> None:
    result = classify_krx_stock(
        minimum_item(certificate_type="우선주")
    )

    assert result.share_class == ShareClass.PREFERRED
    assert result.universe_status == UniverseStatus.REVIEW_REQUIRED


def test_stock_name_is_not_used_to_infer_preferred_share() -> None:
    result = classify_krx_stock(
        minimum_item(
            name="종목명우",
            security_group="주권",
            certificate_type="",
        )
    )

    assert result.share_class == ShareClass.UNKNOWN
    assert result.universe_status == UniverseStatus.REVIEW_REQUIRED


def test_null_official_field_is_not_converted_to_empty_string() -> None:
    payload = minimum_item().model_dump(by_alias=True)
    payload["ISU_NM"] = None

    with pytest.raises(ValidationError):
        KrxStockMasterItem.model_validate(payload)


def test_invalid_listing_date_is_rejected_during_schema_validation() -> None:
    payload = minimum_item().model_dump(by_alias=True)
    payload["LIST_DD"] = "20260230"

    with pytest.raises(ValidationError):
        KrxStockMasterItem.model_validate(payload)


def test_unverified_compound_product_value_is_not_inferred() -> None:
    result = classify_krx_stock(
        minimum_item(security_group="ETF 기타", certificate_type="")
    )

    assert result.product_type == ProductType.OTHER_OFFICIAL
    assert result.universe_status == UniverseStatus.REVIEW_REQUIRED


def test_kospi_membership_uses_only_exact_official_market_value() -> None:
    kospi = classify_krx_stock(minimum_item())
    payload = minimum_item().model_dump(by_alias=True)
    payload["MKT_TP_NM"] = "시장값 미확인"
    unknown = classify_krx_stock(KrxStockMasterItem.model_validate(payload))

    assert kospi.is_kospi is True
    assert unknown.is_kospi is None
    assert unknown.universe_status == UniverseStatus.REVIEW_REQUIRED
