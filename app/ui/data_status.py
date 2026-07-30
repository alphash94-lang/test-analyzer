from __future__ import annotations

import streamlit as st

from app.config import Settings
from app.models.status import ConnectionState, ConnectionStatusItem
from app.services.connection_status import get_connection_statuses

_STATE_ICON = {
    ConnectionState.CONNECTED: "🟢",
    ConnectionState.STALE: "🟡",
    ConnectionState.NOT_CONFIGURED: "🟠",
    ConnectionState.NOT_VERIFIED: "🔵",
    ConnectionState.FAILED: "🔴",
    ConnectionState.DEFERRED: "⚪",
}


def _render_status_card(item: ConnectionStatusItem) -> None:
    with st.container(border=True):
        provider_column, status_column = st.columns([3, 2])
        with provider_column:
            st.subheader(item.provider)
            st.caption(item.detail)
        with status_column:
            st.markdown(f"### {_STATE_ICON[item.state]} {item.state.value}")
            st.caption(f"점검시각 {item.checked_at.strftime('%Y-%m-%d %H:%M:%S KST')}")


def render_data_status(settings: Settings) -> None:
    st.markdown(
        '<div class="status-kicker">System readiness</div>', unsafe_allow_html=True
    )
    st.title("데이터 품질 · API 연결상태")
    st.write(
        "인증정보 설정 여부와 데이터베이스 상태를 확인합니다. "
        "외부 API의 실제 연결 성공은 읽기 전용 검증 호출 이후에만 표시됩니다."
    )
    st.info(
        "추천 계산 가능 여부는 저장된 Phase 2 종목 스냅샷과 Phase 3 "
        "시장 스냅샷을 함께 확인한 뒤 추천종목 화면에 표시합니다."
    )

    statuses = get_connection_statuses(settings)
    for item in statuses:
        _render_status_card(item)

    st.divider()
    st.caption(
        "API 키, 토큰, 계좌번호는 화면과 로그에 표시하지 않습니다. "
        "시장·종목·가격·재무 숫자는 수집 및 검증 전까지 표시하지 않습니다."
    )
