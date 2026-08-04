from __future__ import annotations

import streamlit as st


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at 80% 0%, rgba(35, 92, 176, 0.18), transparent 32rem),
                #07111f;
            color: #f2f6ff;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #081426 0%, #07101d 100%);
            border-right: 1px solid rgba(133, 161, 201, 0.16);
        }
        [data-testid="stSidebar"] * {
            color: #dbe7f8;
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        .block-container {
            max-width: 1120px;
            padding-top: 2.8rem;
            padding-bottom: 3rem;
        }
        .status-title {
            letter-spacing: -0.03em;
            margin-bottom: 0.15rem;
        }
        .status-kicker {
            color: #4387ff;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .muted {
            color: #91a3bd;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
