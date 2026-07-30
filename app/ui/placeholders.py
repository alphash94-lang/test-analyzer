from __future__ import annotations

import streamlit as st


def render_unavailable_page(title: str, phase: str) -> None:
    st.title(title)
    st.info(f"{phase}에서 구현할 기능입니다.")
    st.warning(
        "데이터 연결 필요. 검증된 핵심 데이터가 없어 현재 기능을 사용할 수 없습니다.",
        icon="⚠️",
    )
    st.caption(
        "샘플 종목, 가짜 가격, 배당수익률, RSI, 점수, 추천, 시장국면, "
        "백테스트 결과를 대신 표시하지 않습니다."
    )


def render_settings_page() -> None:
    st.title("설정")
    st.info("환경변수는 저장소 루트의 `.env`에서 관리합니다.")
    st.warning(
        "인증정보는 이 화면에 입력하거나 표시하지 않습니다. "
        "설정 후 데이터 연결상태 화면에서 구성 여부만 확인하세요.",
        icon="🔐",
    )
