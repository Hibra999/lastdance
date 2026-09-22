from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from lastdance.data.alpaca import equivalent_symbol, fetch_crypto_bars
from lastdance.data.downloader import download_alpaca_data


class Response:
    status_code = 200

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


def test_alpaca_historical_crypto_allows_anonymous_requests(monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    frame, _ = fetch_crypto_bars(
        "BTC/USD",
        "4h",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        session=Session(),
    )
    assert len(frame) == 1


def test_alpaca_cache_skips_already_covered_history(tmp_path: Path) -> None:
    cache_dir = tmp_path / "alpaca"
    cache_dir.mkdir()
    pd.DataFrame(
        {
            "date": pd.date_range("2022-12-30", "2023-01-10", tz="UTC"),
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 2.0,
        }
    ).to_feather(cache_dir / "BTC_USD-1d.feather")
    result = download_alpaca_data(
        ["BTC/USD"],
        ["1d"],
        "20230103-",
        startup_candles=2,
        data_dir=cache_dir,
        now=datetime(2023, 1, 11, tzinfo=UTC),
    )
    assert result["request_count"] == 0
    assert result["files"][0]["cache_hit"] is True


def test_alpaca_cache_remembers_empty_provider_history(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def empty_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), {
            "pages": 1
        }

    monkeypatch.setattr("lastdance.data.downloader.fetch_crypto_bars", empty_fetch)
    kwargs = {
        "pairs": ["MISSING/USD"],
        "timeframes": ["1d"],
        "timerange": "20230103-",
        "startup_candles": 2,
        "data_dir": tmp_path / "alpaca",
        "now": datetime(2023, 1, 11, tzinfo=UTC),
    }
    first = download_alpaca_data(**kwargs)
    second = download_alpaca_data(**kwargs)

    assert first["request_count"] == 1
    assert second["request_count"] == 0
    assert second["files"][0]["history_cache_hit"] is True
    assert calls == 1


def test_alpaca_daily_preflight_skips_invalid_intraday_downloads(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_fetch(pair, timeframe, start, end):
        calls.append((pair, timeframe))
        timestamps = (
            pd.date_range("2023-01-01", periods=3, freq="1D", tz="UTC")
            if pair == "BTC/USD" and timeframe == "1d"
            else pd.DatetimeIndex([pd.Timestamp(start)])
            if pair == "BTC/USD"
            else pd.DatetimeIndex([])
        )
        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 2.0,
            }
        )
        return frame, {"pages": 1}

    monkeypatch.setattr("lastdance.data.downloader.fetch_crypto_bars", fake_fetch)
    result = download_alpaca_data(
        ["BTC/USD", "MISSING/USD"],
        ["5m", "1d"],
        "20230103-",
        startup_candles=2,
        data_dir=tmp_path / "alpaca",
        now=datetime(2023, 1, 4, tzinfo=UTC),
    )

    assert calls == [("BTC/USD", "1d"), ("MISSING/USD", "1d"), ("BTC/USD", "5m")]
    assert result["preflight_eligible_pairs"] == ["BTC/USD"]
    assert result["preflight_excluded_pairs"] == ["MISSING/USD"]
