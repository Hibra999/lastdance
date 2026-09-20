from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lastdance.data.alpaca import equivalent_symbol, fetch_crypto_bars


class Response:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "bars": {
                "BTC/USD": [
                    {"t": "2026-01-01T00:00:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 5}
                ]
            },
            "next_page_token": None,
        }


class Session:
    def get(self, url, headers, params, timeout):
        assert "APCA-API-KEY-ID" in headers
        assert params["symbols"] == "BTC/USD"
        return Response()


def test_alpaca_provenance_is_unambiguous(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    frame, provenance = fetch_crypto_bars(
        "BTC/USD",
        "5m",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        session=Session(),
    )
    assert len(frame) == 1
    assert provenance["data_source"] == "alpaca"
    assert provenance["proxy_market_data"] is True


def test_alpaca_rejects_non_usd_proxy() -> None:
    with pytest.raises(ValueError):
        equivalent_symbol("BTC/MXN")
