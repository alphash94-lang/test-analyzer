from __future__ import annotations

import streamlit as st

from app.config import get_settings
from app.logging_config import configure_logging
from app.ui.backtest import render_backtest
from app.ui.data_status import render_data_status
from app.ui.events import render_events
from app.ui.krx_preview import render_krx_preview
from app.ui.market_dashboard import render_market_dashboard
from app.ui.placeholders import render_settings_page, render_unavailable_page
from app.ui.portfolio import render_portfolio
from app.ui.recommendations import render_recommendations
from app.ui.stock_search import render_stock_search
from app.ui.styles import apply_styles

MENU_PHASES: dict[str, str] = {}
API_PREVIEW_MENU = "통합 API 미리보기"
STOCK_SEARCH_MENU = "개별 종목 검색"
RECOMMENDATIONS_MENU = "추천종목"


def main() -> None:
    st.set_page_config(
        page_title="코스피 배당주 저평가·시장회복 분석기",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    apply_styles()

    with st.sidebar:
        st.markdown("## 📈 KOSPI Analyzer")
        st.caption("Phase 7 · 통합 검증·배포 준비")
        selected = st.radio(
            "메뉴",
            [
                "데이터 연결상태",
                STOCK_SEARCH_MENU,
                "시장국면 대시보드",
                RECOMMENDATIONS_MENU,
                "포트폴리오",
                "공시·뉴스",
                "백테스트",
                API_PREVIEW_MENU,
                *MENU_PHASES.keys(),
                "설정",
            ],
            label_visibility="collapsed",
            key="main_menu",
        )
        st.divider()
        st.caption("읽기 전용 · 자동주문 기능 없음")

    if selected != STOCK_SEARCH_MENU:
        st.session_state.pop("stock_detail_origin", None)
        st.session_state.pop("stock_detail_recommendation", None)
        st.session_state.pop("stock_search_query", None)

    if selected == "데이터 연결상태":
        render_data_status(settings)
    elif selected == STOCK_SEARCH_MENU:
        render_stock_search(settings)
    elif selected == "시장국면 대시보드":
        render_market_dashboard(settings)
    elif selected == RECOMMENDATIONS_MENU:
        render_recommendations(settings)
    elif selected == "포트폴리오":
        render_portfolio(settings)
    elif selected == "공시·뉴스":
        render_events(settings)
    elif selected == "백테스트":
        render_backtest(settings)
    elif selected == API_PREVIEW_MENU:
        render_krx_preview(settings)
    elif selected == "설정":
        render_settings_page()
    else:
        render_unavailable_page(selected, MENU_PHASES[selected])


if __name__ == "__main__":
    main()
