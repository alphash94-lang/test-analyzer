from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

import httpx
import websockets

from app.config import Settings
from app.models.realtime_market import RealtimeIndexTick, RealtimeStockTick
from app.utils.dates import SEOUL

KIS_APPROVAL_ENDPOINT = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
KIS_WEBSOCKET_URL = "ws://ops.koreainvestment.com:21000/tryitout"
KIS_INDEX_TR_ID = "H0UPCNT0"
KIS_STOCK_TR_ID = "H0STCNT0"


class KisRealtimeProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream(
        self,
        symbols: Sequence[str] | None = None,
    ) -> AsyncIterator[RealtimeIndexTick | RealtimeStockTick]:
        approval_key = await self._approval_key()
        async with websockets.connect(
            KIS_WEBSOCKET_URL,
            ping_interval=None,
            open_timeout=self.settings.http_timeout_seconds,
        ) as websocket:
            stock_symbols = tuple(
                dict.fromkeys(
                    symbols
                    or (
                        self.settings.phase3_samsung_symbol,
                        self.settings.phase3_sk_hynix_symbol,
                    )
                )
            )
            subscriptions = (
                (KIS_INDEX_TR_ID, "0001"),
                *((KIS_STOCK_TR_ID, symbol) for symbol in stock_symbols),
            )
            for tr_id, tr_key in subscriptions:
                await websocket.send(
                    json.dumps(
                        {
                            "header": {
                                "approval_key": approval_key,
                                "custtype": "P",
                                "tr_type": "1",
                                "content-type": "utf-8",
                            },
                            "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
                        }
                    )
                )
                await asyncio.sleep(0.5)

            async for raw in websocket:
                if not isinstance(raw, str):
                    continue
                if raw.startswith("{"):
                    payload = json.loads(raw)
                    if payload.get("header", {}).get("tr_id") == "PINGPONG":
                        await websocket.pong(raw.encode("utf-8"))
                    continue
                tick = self.parse_message(raw)
                if tick is not None:
                    yield tick

    async def _approval_key(self) -> str:
        credentials = self._credentials()
        if credentials is None:
            raise ValueError("KIS_APP_KEY and KIS_APP_SECRET are required")
        app_key, app_secret = credentials
        async with httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        ) as client:
            response = await client.post(
                KIS_APPROVAL_ENDPOINT,
                headers={"content-type": "application/json"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": app_key,
                    "secretkey": app_secret,
                },
            )
            response.raise_for_status()
            key = response.json().get("approval_key")
            if not isinstance(key, str) or not key:
                raise ValueError("KIS approval response omitted approval_key")
            return key

    def _credentials(self) -> tuple[str, str] | None:
        if self.settings.kis_app_key is None or self.settings.kis_app_secret is None:
            return None
        return (
            self.settings.kis_app_key.get_secret_value(),
            self.settings.kis_app_secret.get_secret_value(),
        )

    @staticmethod
    def parse_message(
        raw: str,
    ) -> RealtimeIndexTick | RealtimeStockTick | None:
        parts = raw.split("|", 3)
        if len(parts) != 4 or parts[0] != "0":
            return None
        tr_id, payload = parts[1], parts[3]
        fields = payload.split("^")
        try:
            if tr_id == KIS_INDEX_TR_ID and len(fields) >= 30:
                as_of_at = _market_timestamp(fields[1])
                return RealtimeIndexTick(
                    as_of_at=as_of_at,
                    level=_decimal(fields[2]),
                    change_rate=_decimal(fields[9]),
                    advancing_count=int(fields[23]),
                    unchanged_count=int(fields[24]),
                    declining_count=int(fields[25]),
                )
            if tr_id == KIS_STOCK_TR_ID and len(fields) >= 46:
                return RealtimeStockTick(
                    symbol=fields[0],
                    as_of_at=_market_timestamp(fields[1], fields[33]),
                    price=_decimal(fields[2]),
                    change_rate=_decimal(fields[5]),
                )
        except InvalidOperation, ValueError:
            return None
        return None


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "").strip())


def _market_timestamp(clock: str, date_value: str | None = None) -> datetime:
    day = (
        date(
            int(date_value[:4]),
            int(date_value[4:6]),
            int(date_value[6:8]),
        )
        if date_value and len(date_value) == 8
        else datetime.now(tz=SEOUL).date()
    )
    normalized = clock.strip().zfill(6)
    parsed_time = time(
        hour=int(normalized[:2]),
        minute=int(normalized[2:4]),
        second=int(normalized[4:6]),
    )
    return datetime.combine(day, parsed_time, tzinfo=SEOUL)
