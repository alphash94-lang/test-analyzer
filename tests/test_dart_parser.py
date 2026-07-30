from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from app.providers.dart import DartApiError, parse_dart_corp_codes


def zipped_xml(xml: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buffer.getvalue()


def test_parse_minimum_official_corp_code_fields() -> None:
    raw = zipped_xml(
        """
        <result>
          <list>
            <corp_code>00123456</corp_code>
            <corp_name>파서검증</corp_name>
            <corp_eng_name>Parser Check</corp_eng_name>
            <stock_code>000001</stock_code>
            <modify_date>20260729</modify_date>
          </list>
        </result>
        """
    )

    records = parse_dart_corp_codes(raw)

    assert len(records) == 1
    assert records[0].corp_code == "00123456"
    assert records[0].stock_code == "000001"
    assert records[0].modify_date.isoformat() == "2026-07-29"


def test_parse_alphanumeric_stock_code() -> None:
    raw = zipped_xml(
        """
        <result>
          <list>
            <corp_code>00123456</corp_code>
            <corp_name>영문종목코드</corp_name>
            <corp_eng_name>Alphanumeric Code</corp_eng_name>
            <stock_code>A00001</stock_code>
            <modify_date>20260729</modify_date>
          </list>
        </result>
        """
    )

    records = parse_dart_corp_codes(raw)

    assert records[0].stock_code == "A00001"


@pytest.mark.parametrize("stock_code", ["A0001", "a00001", "A0000-"])
def test_invalid_alphanumeric_stock_code_is_rejected(stock_code: str) -> None:
    raw = zipped_xml(
        f"""
        <result>
          <list>
            <corp_code>00123456</corp_code>
            <corp_name>잘못된종목코드</corp_name>
            <corp_eng_name>Invalid Code</corp_eng_name>
            <stock_code>{stock_code}</stock_code>
            <modify_date>20260729</modify_date>
          </list>
        </result>
        """
    )

    with pytest.raises(ValueError, match="stock_code"):
        parse_dart_corp_codes(raw)


def test_dart_error_xml_is_not_treated_as_corp_data() -> None:
    with pytest.raises(DartApiError) as captured:
        parse_dart_corp_codes(
            b"<result><status>010</status><message>invalid</message></result>"
        )

    assert captured.value.code == "010"


def test_plain_success_xml_is_rejected_because_contract_requires_zip() -> None:
    with pytest.raises(ValueError, match="ZIP"):
        parse_dart_corp_codes(
            """
            <result>
              <list>
                <corp_code>00123456</corp_code>
                <corp_name>형식검증</corp_name>
                <corp_eng_name>Format Check</corp_eng_name>
                <stock_code>000001</stock_code>
                <modify_date>20260729</modify_date>
              </list>
            </result>
            """.encode()
        )


def test_missing_required_xml_element_is_not_converted_to_empty_string() -> None:
    raw = zipped_xml(
        """
        <result>
          <list>
            <corp_code>00123456</corp_code>
            <corp_eng_name>Missing Name</corp_eng_name>
            <stock_code>000001</stock_code>
            <modify_date>20260729</modify_date>
          </list>
        </result>
        """
    )

    with pytest.raises(ValueError, match="corp_name"):
        parse_dart_corp_codes(raw)


def test_present_but_blank_optional_elements_remain_blank_or_missing() -> None:
    raw = zipped_xml(
        """
        <result>
          <list>
            <corp_code>00123456</corp_code>
            <corp_name>선택필드검증</corp_name>
            <corp_eng_name />
            <stock_code />
            <modify_date>20260729</modify_date>
          </list>
        </result>
        """
    )

    records = parse_dart_corp_codes(raw)

    assert records[0].corp_eng_name == ""
    assert records[0].stock_code is None
