from __future__ import annotations

import ccxt
import pytest
from freqtrade.exchange import validate_exchange

from lastdance.exchanges.bitso import freqtrade_compatibility_report


def test_freqtrade_accepts_bitso_spot() -> None:
    valid, reason, _, _ = validate_exchange("bitso")
    assert valid, reason


def test_freqtrade_report_records_limitations() -> None:
    report = freqtrade_compatibility_report()
    assert report["exchange_valid"] is True
    assert report["configured_mode"] == "spot"
    assert "fetchTickers" in report["spot_limitations"]


def test_ccxt_bitso_capability_contract() -> None:
    exchange = ccxt.bitso()
    assert exchange.has["fetchOHLCV"] is True
    assert exchange.has["createOrder"] is True
    assert exchange.has["cancelOrder"] is True
    assert exchange.has["fetchTickers"] is False


@pytest.mark.integration
def test_bitso_public_markets_reachable() -> None:
    markets = ccxt.bitso({"enableRateLimit": True}).load_markets()
    assert "BTC/USD" in markets
    assert markets["BTC/USD"]["spot"] is True
