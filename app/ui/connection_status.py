from __future__ import annotations

from hashlib import sha256

import streamlit as st

from app.config import Settings
from app.models.status import ConnectionStatusItem
from app.services.connection_status import get_connection_statuses


@st.cache_data(ttl=30, max_entries=20, show_spinner=False)
def _cached_connection_statuses(
    settings_fingerprint: str,
    _settings: Settings,
) -> list[ConnectionStatusItem]:
    """Reuse the stored provider-state query across UI sections and reruns."""

    del settings_fingerprint
    return get_connection_statuses(_settings)


def cached_connection_statuses(settings: Settings) -> list[ConnectionStatusItem]:
    fingerprint_source = "|".join(
        (
            settings.database_url,
            str(bool(settings.krx_api_key)),
            str(bool(settings.dart_api_key)),
            str(bool(settings.kis_app_key)),
            str(bool(settings.kis_app_secret)),
            str(bool(settings.naver_client_id)),
            str(bool(settings.naver_client_secret)),
            str(bool(settings.ecos_api_key)),
            str(settings.data_freshness_warning_hours),
        )
    )
    fingerprint = sha256(fingerprint_source.encode("utf-8")).hexdigest()
    return _cached_connection_statuses(fingerprint, settings)
