"""Exchange client unit tests: spot-order body + signing (no network)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from app.exchange.coindcx import CoinDCXClient


def _fake_settings(monkeypatch):
    monkeypatch.setattr("app.exchange.coindcx.settings.coindcx_api_key", "k", raising=False)
    monkeypatch.setattr("app.exchange.coindcx.settings.coindcx_api_secret", "s", raising=False)


async def test_create_spot_order_body_and_sign(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()
    captured = {}

    async def fake_post(path, *, content=None, headers=None):
        captured["path"] = path
        captured["body"] = content
        captured["headers"] = headers
        return httpx.Response(200, json={"status": "ok", "orders": [{"id": "1"}]})

    # Patch the instance's private httpx client (no network). The signed
    # payload + headers are captured before the transport is reached.
    monkeypatch.setattr(cli._priv, "post", fake_post)

    res = await cli.create_spot_order(
        side="buy", pair="BTCINR", order_type="market_order", quantity=0.1
    )
    assert res["status"] == "ok"

    # Signature is hmac-sha256 of the actual signed payload (captured content)
    # with secret "s" — derived from the captured content, not hardcoded.
    payload = captured["body"]
    sig = hmac.new(b"s", payload.encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["X-AUTH-APIKEY"] == "k"
    assert captured["headers"]["X-AUTH-SIGNATURE"] == sig

    # Spot endpoint path.
    assert captured["path"] == "/exchange/v1/orders/create"

    # Body is nested under 'order' with a millisecond timestamp.
    body = json.loads(payload)
    assert "timestamp" in body
    assert body["order"]["side"] == "buy"
    assert body["order"]["pair"] == "BTCINR"
    assert body["order"]["total_quantity"] == 0.1
    assert "price" not in body["order"]  # market order -> no price

    # _sign uses sort_keys=True, so 'order' comes before 'timestamp'.
    assert payload.index('"order"') < payload.index('"timestamp"')


async def test_create_spot_order_limit_includes_price(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()
    captured = {}

    async def fake_post(path, *, content=None, headers=None):
        captured["body"] = content
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(cli._priv, "post", fake_post)

    await cli.create_spot_order(
        side="sell", pair="BTCINR", order_type="limit_order", quantity=0.05, price=500000.0
    )
    body = json.loads(captured["body"])
    assert body["order"]["price"] == 500000.0
    assert body["order"]["order_type"] == "limit_order"


async def test_create_spot_order_rejects_bad_inputs(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()

    import pytest

    for kwargs, msg in [
        ({"side": "buyx", "pair": "BTCINR", "order_type": "market_order", "quantity": 0.1}, "side"),
        ({"side": "buy", "pair": "BTCINR", "order_type": "stop_market", "quantity": 0.1}, "order_type"),
        ({"side": "buy", "pair": "BTCINR", "order_type": "market_order", "quantity": 0}, "quantity"),
    ]:
        with pytest.raises(ValueError, match=msg):
            await cli.create_spot_order(**kwargs)


async def test_get_conversion_rate_seconds_ts(monkeypatch):
    _fake_settings(monkeypatch)
    cli = CoinDCXClient()
    captured = {}

    async def fake_post(path, *, content=None, headers=None):
        captured["path"] = path
        captured["body"] = content
        captured["headers"] = headers
        return httpx.Response(200, json=[{"symbol": "USDTINR",
                "margin_currency_short_name": "INR", "target_currency_short_name": "USDT",
                "conversion_price": 89.12, "last_updated_at": 1728460492399}])

    monkeypatch.setattr(cli._priv, "post", fake_post)
    price = await cli.get_conversion_rate()
    assert abs(price - 89.12) < 1e-9
    assert captured["path"] == "/api/v1/derivatives/futures/data/conversions"
    body = json.loads(captured["body"])
    # SECONDS timestamp (not ms like other endpoints) — the load-bearing gotcha.
    assert abs(body["timestamp"] - int(time.time())) < 5, "conversion ts must be seconds"
    assert body["timestamp"] < 1e12, "ms ts would be >1e12"
    sig = hmac.new(b"s", captured["body"].encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["X-AUTH-SIGNATURE"] == sig
