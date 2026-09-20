from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lastdance.exchanges import bitso


class FakeExchange:
    id = "bitso"
    has = {name: True for name in bitso.CAPABILITY_KEYS}
    timeframes = {"5m": "300"}

    def load_markets(self) -> dict[str, dict[str, Any]]:
        return {
            "BTC/USD": {"quote": "USD", "base": "BTC", "active": True, "spot": True},
            "FOO3L/USD": {"quote": "USD", "base": "FOO3L", "active": True, "spot": True},
            "EUR/USD": {"quote": "USD", "base": "EUR", "active": True, "spot": True},
            "DEAD/USD": {"quote": "USD", "base": "DEAD", "active": False, "spot": True},
            "ETH/MXN": {"quote": "MXN", "base": "ETH", "active": True, "spot": True},
        }


def test_pair_filtering_records_reasons(monkeypatch: Any) -> None:
    monkeypatch.setattr(bitso, "create_exchange", lambda: FakeExchange())
    report = bitso.discover_usd_universe()
    assert report["pairs_used"] == ["BTC/USD"]
    excluded = {item["pair"]: item["reason"] for item in report["pairs_excluded"]}
    assert "leveraged" in excluded["FOO3L/USD"].lower()
    assert "Fiat/fiat" in excluded["EUR/USD"]
    assert "inactive_market" in excluded["DEAD/USD"]


def test_capability_report_is_explicit() -> None:
    report = bitso.capability_report(FakeExchange())
    assert set(report["capabilities"]) == set(bitso.CAPABILITY_KEYS)
    assert report["capabilities"]["fetchOHLCV"] is True


def test_time_synchronization_uses_http_date() -> None:
    now = datetime(2026, 9, 20, 2, 0, 10, tzinfo=UTC)
    report = bitso._time_synchronization({"Date": "Sun, 20 Sep 2026 02:00:00 GMT"}, now=now)
    assert report["checked"] is True
    assert report["offset_seconds"] == -10
    assert report["within_30_seconds"] is True
