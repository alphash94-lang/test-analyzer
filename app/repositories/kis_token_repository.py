from __future__ import annotations

import base64
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from hashlib import sha256

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.authentication import KisAccessToken
from app.db.session import create_db_engine, create_session_factory
from app.utils.dates import now_kst, restore_database_kst

logger = logging.getLogger(__name__)

TokenRefresh = Callable[
    [],
    Awaitable[tuple[str | None, datetime | None, str | None]],
]
TokenResult = tuple[str | None, datetime | None, str | None]


class KisTokenRepository:
    """Persist encrypted KIS tokens and serialize refreshes per credential."""

    def __init__(self, settings: Settings) -> None:
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def get_or_refresh(
        self,
        *,
        app_key: str,
        app_secret: str,
        refresh: TokenRefresh,
    ) -> TokenResult:
        fingerprint = self.credential_fingerprint(app_key, app_secret)
        encryption_key = self._encryption_key(app_key, app_secret)
        refresh_result: TokenResult | None = None
        try:
            with self._sessions() as session:
                cached = self._load(
                    session,
                    fingerprint=fingerprint,
                    encryption_key=encryption_key,
                )
                if cached is not None:
                    return cached[0], cached[1], None

            with self._sessions.begin() as session:
                self._acquire_refresh_lock(session, fingerprint)
                cached = self._load(
                    session,
                    fingerprint=fingerprint,
                    encryption_key=encryption_key,
                )
                if cached is not None:
                    return cached[0], cached[1], None

                refresh_result = await refresh()
                token, expires_at, error = refresh_result
                if token is not None and expires_at is not None and error is None:
                    self._save(
                        session,
                        fingerprint=fingerprint,
                        encryption_key=encryption_key,
                        token=token,
                        expires_at=expires_at,
                    )
                return refresh_result
        except (SQLAlchemyError, OSError, InvalidTag, ValueError) as exc:
            logger.warning(
                "KIS persistent token cache unavailable: %s",
                type(exc).__name__,
            )
            if refresh_result is not None:
                return refresh_result
            return await refresh()

    def invalidate(
        self,
        *,
        app_key: str,
        app_secret: str,
        rejected_token: str,
    ) -> None:
        fingerprint = self.credential_fingerprint(app_key, app_secret)
        encryption_key = self._encryption_key(app_key, app_secret)
        try:
            with self._sessions.begin() as session:
                row = session.get(KisAccessToken, fingerprint)
                if row is None:
                    return
                try:
                    stored_token = self._decrypt(
                        row.encrypted_token,
                        encryption_key,
                    )
                except InvalidTag, UnicodeDecodeError, ValueError:
                    stored_token = rejected_token
                if stored_token == rejected_token:
                    session.delete(row)
        except (SQLAlchemyError, OSError, ValueError) as exc:
            logger.warning(
                "KIS persistent token invalidation failed: %s",
                type(exc).__name__,
            )

    @staticmethod
    def credential_fingerprint(app_key: str, app_secret: str) -> str:
        return sha256(f"{app_key}\0{app_secret}".encode()).hexdigest()

    @staticmethod
    def _encryption_key(app_key: str, app_secret: str) -> bytes:
        return sha256(
            b"kis-token-cache-v1\0"
            + app_key.encode("utf-8")
            + b"\0"
            + app_secret.encode("utf-8")
        ).digest()

    @staticmethod
    def _encrypt(token: str, encryption_key: bytes) -> str:
        nonce = os.urandom(12)
        ciphertext = AESGCM(encryption_key).encrypt(
            nonce,
            token.encode("utf-8"),
            b"kis-access-token-v1",
        )
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    @staticmethod
    def _decrypt(encrypted_token: str, encryption_key: bytes) -> str:
        payload = base64.urlsafe_b64decode(encrypted_token.encode("ascii"))
        if len(payload) <= 12:
            raise ValueError("invalid encrypted KIS token payload")
        plaintext = AESGCM(encryption_key).decrypt(
            payload[:12],
            payload[12:],
            b"kis-access-token-v1",
        )
        token = plaintext.decode("utf-8").strip()
        if not token:
            raise ValueError("empty decrypted KIS token")
        return token

    def _load(
        self,
        session: Session,
        *,
        fingerprint: str,
        encryption_key: bytes,
    ) -> tuple[str, datetime] | None:
        row = session.get(KisAccessToken, fingerprint)
        if row is None:
            return None
        expires_at = restore_database_kst(row.expires_at)
        if now_kst() >= expires_at:
            return None
        try:
            token = self._decrypt(row.encrypted_token, encryption_key)
        except InvalidTag, UnicodeDecodeError, ValueError:
            return None
        return token, expires_at

    def _save(
        self,
        session: Session,
        *,
        fingerprint: str,
        encryption_key: bytes,
        token: str,
        expires_at: datetime,
    ) -> None:
        encrypted_token = self._encrypt(token, encryption_key)
        row = session.get(KisAccessToken, fingerprint)
        if row is None:
            session.add(
                KisAccessToken(
                    credential_fingerprint=fingerprint,
                    encrypted_token=encrypted_token,
                    expires_at=expires_at,
                    updated_at=now_kst(),
                )
            )
            return
        row.encrypted_token = encrypted_token
        row.expires_at = expires_at
        row.updated_at = now_kst()

    @staticmethod
    def _acquire_refresh_lock(session: Session, fingerprint: str) -> None:
        if session.get_bind().dialect.name != "postgresql":
            return
        lock_id = int.from_bytes(
            bytes.fromhex(fingerprint)[:8],
            byteorder="big",
            signed=True,
        )
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": lock_id},
        )
