"""CoinDCX futures REST client.

Auth: HMAC-SHA256 over JSON body, headers X-AUTH-APIKEY / X-AUTH-SIGNATURE.
Endpoints verified against docs.coindcx.com (2026-07); re-check before live trading.

Two interfaces:
- public_* : market data, no auth (base = public.coindcx.com)
- private_*: trading/positions/wallet, signed (base = api.coindcx.com)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from app.config import settings
from app.logging import get_logger

log = get_logger("exchange.rest")

# ponytail: verify each path against current docs.coindcx.com before live money.
# Source: docs.coindcx.com futures API reference (2026-07).
EP = {
    "instrument": "/exchange/v1/derivatives/futures/data/instrument",
    "candles": "/market_data/candlesticks",
    "create_order": "/exchange/v1/derivatives/futures/orders/create",
    "orders": "/exchange/v1/derivatives/futures/orders",
    "cancel_order": "/exchange/v1/derivatives/futures/orders/cancel",
    "positions": "/exchange/v1/derivatives/futures/positions",
    "exit_position": "/exchange/v1/derivatives/futures/positions/exit",
    "update_leverage": "/exchange/v1/derivatives/futures/positions/update_leverage",
    "wallets": "/exchange/v1/derivatives/futures/wallets",
    "trades": "/exchange/v1/derivatives/futures/trades",
    # Public spot ticker (api.coindcx.com, no auth). USDTINR last_price = USDT/INR FX.
    "ticker": "/exchange/ticker",
    # Spot order (api.coindcx.com, signed). BTCINR spot leg for the carry hedge.
    # ponytail: path from docs.coindcx.com (2026-07); re-check before live money.
    "spot_create_order": "/exchange/v1/orders/create",
    # INR-margined futures USDT<>INR conversion rate (read-only, signed).
    # ponytail: takes a SECONDS timestamp (not ms like other endpoints).
    "conversions": "/api/v1/derivatives/futures/data/conversions",
}

# resolution map: our timeframe -> coindcx candle resolution string
RESOLUTION = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "1H": "60", "4H": "240", "1D": "1D",
}


class CoinDCXError(Exception):
    def __init__(self, msg: str, payload: Any = None, status: int = 0):
        super().__init__(msg)
        self.payload = payload
        self.status = status  # HTTP status; 4xx = deterministic, 5xx = transient

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status < 500


class CoinDCXClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: float = 15.0,
    ):
        self.api_key = api_key if api_key is not None else settings.coindcx_api_key
        self.api_secret = api_secret if api_secret is not None else settings.coindcx_api_secret
        self._pub = httpx.AsyncClient(base_url=settings.public_base, timeout=timeout)
        self._priv = httpx.AsyncClient(base_url=settings.rest_base, timeout=timeout)
        self._rate_lock = asyncio.Lock()  # ponytail: simple rate limit, ~16/s allowed

    async def aclose(self) -> None:
        await self._pub.aclose()
        await self._priv.aclose()

    async def __aenter__(self) -> "CoinDCXClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- auth helpers ---
    def _sign(self, body: dict[str, Any]) -> tuple[dict[str, str], str]:
        payload = json.dumps(body, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {"X-AUTH-APIKEY": self.api_key, "X-AUTH-SIGNATURE": sig,
                    "Content-Type": "application/json"}
        return headers, payload

    async def _signed_post(self, path: str, body: dict[str, Any]) -> Any:
        body = {**body, "timestamp": int(time.time() * 1000)}  # ms per CoinDCX docs
        headers, payload = self._sign(body)
        async with self._rate_lock:
            r = await self._priv.post(path, content=payload, headers=headers)
        return self._handle(r)

    async def _signed_get(self, path: str) -> Any:
        # Futures GET endpoints (wallets) sign the EMPTY body, not a JSON payload.
        sig = hmac.new(self.api_secret.encode(), b"", hashlib.sha256).hexdigest()
        headers = {"X-AUTH-APIKEY": self.api_key, "X-AUTH-SIGNATURE": sig,
                   "Content-Type": "application/json"}
        async with self._rate_lock:
            r = await self._priv.get(path, headers=headers)
        return self._handle(r)

    async def _get(self, base: str, path: str, params: dict[str, Any]) -> Any:
        client = self._pub if "public.coindcx" in base else self._priv
        r = await client.get(path, params=params)
        return self._handle(r)

    @staticmethod
    def _handle(r: httpx.Response) -> Any:
        try:
            data = r.json()
        except ValueError:
            raise CoinDCXError(f"non-json {r.status_code}: {r.text[:200]}", status=r.status_code)
        if r.status_code >= 400:
            # Surface CoinDCX's own message so callers see the real reject reason
            # (e.g. "Take profit trigger price should be higher than last traded price").
            msg = data.get("message") if isinstance(data, dict) else None
            raise CoinDCXError(f"http {r.status_code}: {msg or data}", data, status=r.status_code)
        return data

    # --- public market data ---
    async def get_instrument(self, pair: str, margin: str | None = None) -> dict[str, Any]:
        """Instrument metadata: leverage tiers, fees, min/max qty, tick/lot size.
        margin defaults to settings.margin_currency (INR for this account).
        Endpoint is on api.coindcx.com (rest_base), public GET (no auth)."""
        margin = margin or settings.margin_currency
        r = await self._priv.get(EP["instrument"],
                                 params={"pair": pair, "margin_currency_short_name": margin})
        data = self._handle(r)
        if isinstance(data, dict) and "instrument" in data:
            return data["instrument"]
        return data if isinstance(data, dict) else (data[0] if data else {})

    async def get_candles(
        self, pair: str, timeframe: str, from_ts: int, to_ts: int, pcode: str = "f"
    ) -> list[dict[str, Any]]:
        res = RESOLUTION[timeframe]
        data = await self._get(settings.public_base, EP["candles"], {
            "pair": pair, "from": from_ts, "to": to_ts, "resolution": res, "pcode": pcode,
        })
        if isinstance(data, dict) and data.get("s") == "ok":
            return data.get("data", [])
        return data if isinstance(data, list) else []

    # --- trading ---
    async def create_order(self, params: dict[str, Any]) -> dict[str, Any]:
        """Idempotent create. Body is nested under 'order' with a MILLISECOND
        timestamp per CoinDCX docs (flat body / second-precision timestamps are
        rejected). Caller passes normalized fields via build_order().
        """
        order = {"client_order_id": uuid.uuid4().hex, "notification": "no_notification",
                 "margin_currency_short_name": settings.margin_currency, **params}
        body = {"timestamp": int(time.time() * 1000), "order": order}
        headers, payload = self._sign(body)
        async with self._rate_lock:
            r = await self._priv.post(EP["create_order"], content=payload, headers=headers)
        return self._handle(r)

    async def create_spot_order(
        self, *, side: str, pair: str, order_type: str, quantity: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Spot order (BTCINR hedge leg). Signed POST to the spot create endpoint.
        No leverage/margin fields (spot). Mirrors create_order's signing pattern:
        body = {"timestamp": ms, "order": {...}} -> _sign -> _priv.post.
        """
        if side not in ("buy", "sell"):
            raise ValueError(f"bad side {side}")
        if order_type not in ("market_order", "limit_order"):
            raise ValueError(f"bad spot order_type {order_type}")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        order = {"side": side, "pair": pair, "order_type": order_type,
                 "total_quantity": quantity}
        if price is not None:
            order["price"] = price
        body = {"timestamp": int(time.time() * 1000), "order": order}
        headers, payload = self._sign(body)
        async with self._rate_lock:
            r = await self._priv.post(EP["spot_create_order"], content=payload, headers=headers)
        return self._handle(r)

    async def cancel_order(self, order_id: str) -> Any:
        return await self._signed_post(EP["cancel_order"], {"id": order_id})

    async def get_positions(self, pair: str | None = None) -> list[dict[str, Any]]:
        """Fetch futures positions. Body must include page+size (required) and
        margin_currency_short_name as an ARRAY (default ["USDT"] — INR positions
        are hidden unless ["INR"] requested). Filter via `pairs` (string). Response
        normalized to our field names (active_pos→position_size, avg_price→avg_entry_price)."""
        body: dict[str, Any] = {
            "page": "1", "size": "100",
            "margin_currency_short_name": [settings.margin_currency],
        }
        if pair:
            body["pairs"] = pair
        data = await self._signed_post(EP["positions"], body)
        rows = data if isinstance(data, list) else (data.get("data", []) if isinstance(data, dict) else [])
        out = []
        for r in rows:
            size = float(r.get("active_pos", 0) or 0)
            out.append({
                "id": r.get("id"), "pair": r.get("pair"),
                "position_size": size,
                "avg_entry_price": float(r.get("avg_price", 0) or 0),
                "liquidation_price": float(r.get("liquidation_price", 0) or 0) or None,
                "leverage": int(float(r.get("leverage", 1) or 1)),
                "margin_type": r.get("margin_type"),
                "side": "long" if size >= 0 else "short",
                "stop_loss": float(r["stop_loss_trigger"]) if r.get("stop_loss_trigger") else None,
                "take_profit": float(r["take_profit_trigger"]) if r.get("take_profit_trigger") else None,
                "mark_price": float(r.get("mark_price", 0) or 0),
            })
        return out

    async def exit_position(self, position_id: str) -> Any:
        return await self._signed_post(EP["exit_position"], {"id": position_id})

    async def update_leverage(self, pair: str, leverage: int, margin_type: str = "isolated") -> Any:
        return await self._signed_post(EP["update_leverage"], {
            "pair": pair, "leverage": leverage, "position_margin_type": margin_type,
        })

    async def get_wallets(self) -> Any:
        return await self._signed_get(EP["wallets"])

    async def get_usdt_inr(self) -> float:
        """Spot USDT/INR rate from public ticker (no auth).

        ponytail: CoinDCX INR-margined futures actually settle via a platform
        'INR Conversion Rate' that tracks spot USDTINR closely but isn't
        identical. Used here as the FX proxy for sizing + PnL conversion.
        Re-check vs the platform conversion rate before relying on exactness.
        """
        return await self._ticker_price("USDTINR")

    async def get_conversion_rate(self) -> float:
        """Current USDT<>INR conversion rate for INR-margined futures (read-only,
        signed). Endpoint /api/v1/derivatives/futures/data/conversions takes a
        SECONDS timestamp (not ms like other endpoints). Returns conversion_price.
        This rate is NOT spot USDTINR — the gap is the §29 FX-leg hedge leak."""
        body = {"timestamp": int(time.time())}  # SECONDS — load-bearing gotcha
        headers, payload = self._sign(body)
        async with self._rate_lock:
            r = await self._priv.post(EP["conversions"], content=payload, headers=headers)
        data = self._handle(r)
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if str(row.get("symbol", "")).upper() == "USDTINR":
                return float(row["conversion_price"])
        # fallback: first row with a conversion_price
        for row in rows:
            if row.get("conversion_price") is not None:
                return float(row["conversion_price"])
        raise CoinDCXError("no conversion_price in conversions response", data)

    async def get_last_price(self, symbol: str) -> float:
        """Last spot price for symbol from public ticker (no auth).

        ponytail: spot ticker (BTCUSDT) used as proxy for the futures perp
        mark — small basis differs. Only used for sizing/stop/fee estimates
        on manual market orders; the exchange fills at its own price.
        """
        # B-BTC_USDT -> BTCUSDT: strip B- prefix + drop underscore (spot ticker
        # markets have no separator).
        mkt = symbol[2:] if symbol.startswith("B-") else symbol
        mkt = mkt.replace("_", "")
        return await self._ticker_price(mkt)

    async def _ticker_price(self, market: str) -> float:
        r = await self._priv.get(EP["ticker"])
        data = self._handle(r)
        for m in data:
            if m.get("market") == market:
                return float(m["last_price"])
        raise CoinDCXError(f"{market} missing from ticker")


def build_order(
    *, side: str, pair: str, order_type: str, quantity: float,
    price: float | None = None, stop_price: float | None = None,
    leverage: int | None = None, time_in_force: str = "good_till_cancel",
    take_profit_price: float | None = None, stop_loss_price: float | None = None,
    position_margin_type: str = "isolated",
) -> dict[str, Any]:
    """Normalize an order dict for CoinDCX create_order. Validation here."""
    if side not in ("buy", "sell"):
        raise ValueError(f"bad side {side}")
    if order_type not in (
        "market_order", "limit_order", "stop_market", "stop_limit",
        "take_profit_market", "take_profit_limit",
    ):
        raise ValueError(f"bad order_type {order_type}")
    if quantity <= 0:
        raise ValueError("quantity must be > 0")

    o: dict[str, Any] = {
        "side": side,
        "pair": pair,
        "order_type": order_type,
        "total_quantity": quantity,
        "position_margin_type": position_margin_type,
    }
    # time_in_force must be null/omitted for market orders (CoinDCX rejects it).
    if order_type != "market_order":
        o["time_in_force"] = time_in_force
    if price is not None:
        o["price"] = price
    if stop_price is not None:
        o["stop_price"] = stop_price
    if leverage is not None:
        o["leverage"] = leverage
    if take_profit_price is not None:
        o["take_profit_price"] = take_profit_price
    if stop_loss_price is not None:
        o["stop_loss_price"] = stop_loss_price
    return o