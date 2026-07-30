from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Final

_SENSITIVE_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![A-Za-z0-9_])("
    r"x-ncp-apigw-api-key(?:-id)?|crtfc_key|service[_-]?key|"
    r"auth[_-]?key|api[_-]?key|apikey|app[_-]?key|appkey|"
    r"app[_-]?secret|appsecret|access[_-]?token|account[_-]?no|"
    r"client[_-]?(?:id|secret)|authorization"
    r")(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_CREDENTIAL: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\b(?:authorization\s*[:=]\s*)?bearer\s+)[^\s,;]+"
)
_URI_USERINFO: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@/\s]+@"
)
_SECRET_FIELDS: Final[tuple[str, ...]] = (
    "krx_api_key",
    "dart_api_key",
    "kis_app_key",
    "kis_app_secret",
    "kis_account_no",
    "ncp_apigw_api_key_id",
    "ncp_apigw_api_key",
    "naver_client_id",
    "naver_client_secret",
    "bok_api_key",
    "ecos_api_key",
)


def _configured_secret_values(settings: object | None) -> tuple[str, ...]:
    if settings is None:
        return ()
    values: list[str] = []
    for field_name in _SECRET_FIELDS:
        value = getattr(settings, field_name, None)
        getter = getattr(value, "get_secret_value", None)
        if not callable(getter):
            continue
        secret = str(getter()).strip()
        if secret:
            values.append(secret)
    return tuple(values)


def redact_sensitive_text(
    text: str,
    *,
    sensitive_values: Iterable[str] = (),
) -> str:
    """Remove credential shapes and configured values from diagnostic text."""

    redacted = _URI_USERINFO.sub(r"\1[REDACTED]@", text)
    redacted = _BEARER_CREDENTIAL.sub(r"\1[REDACTED]", redacted)
    redacted = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    for value in sorted(
        {item for item in sensitive_values if item},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def safe_exception_message(
    exc: BaseException,
    *,
    settings: object | None = None,
) -> str:
    """Return a useful exception detail without exposing configured credentials."""

    message = redact_sensitive_text(
        str(exc),
        sensitive_values=_configured_secret_values(settings),
    ).strip()
    return message or type(exc).__name__


class SensitiveValueFilter(logging.Filter):
    """Redact common credential assignments if a caller logs them accidentally."""

    def __init__(self, sensitive_values: Iterable[str] = ()) -> None:
        super().__init__()
        self._sensitive_values = tuple(sensitive_values)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_sensitive_text(
            message,
            sensitive_values=self._sensitive_values,
        )
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(
    level: str = "INFO",
    *,
    settings: object | None = None,
) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(
        SensitiveValueFilter(_configured_secret_values(settings))
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
