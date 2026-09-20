from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from lastdance.data.normalize import (
    inspect_cache_file,
    normalize_cache_file,
    normalize_ohlcv,
    validate_ohlcv,
)


def test_ohlcv_normalization_and_validation() -> None:
    rows = [
        [2_000, 10, 12, 9, 11, 2],
        [1_000, 9, 11, 8, 10, 1],
        [2_000, 10, 12, 9, 11, 2],
    ]
    frame = normalize_ohlcv(rows)
    result = validate_ohlcv(frame)
    assert result.valid
    assert result.rows == 2
    assert result.duplicate_timestamps == 0


def test_invalid_ohlc_is_detected() -> None:
    frame = normalize_ohlcv([[1_000, 10, 9, 8, 11, 1]])
    result = validate_ohlcv(frame)
    assert not result.valid
    assert result.invalid_ohlc_rows == 1


def test_cache_normalization_merges_identical_shifted_daily_candles(tmp_path: Path) -> None:
    path = tmp_path / "BTC_USD-1d.feather"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-06T00:00:00Z", "2026-08-06T06:00:00Z"]),
            "open": [10.0, 10.0],
            "high": [12.0, 12.0],
            "low": [9.0, 9.0],
            "close": [11.0, 11.0],
            "volume": [2.0, 2.0],
        }
    ).to_feather(path)
    result = normalize_cache_file(path, "1d")
    assert result["merged_duplicates"] == 1
    assert pd.read_feather(path)["date"].tolist() == [pd.Timestamp("2026-08-06T00:00:00Z")]


def test_cache_normalization_rejects_conflicting_candles(tmp_path: Path) -> None:
    path = tmp_path / "BTC_USD-1d.feather"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-06T00:00:00Z", "2026-08-06T06:00:00Z"]),
            "open": [10.0, 10.0],
            "high": [12.0, 13.0],
            "low": [9.0, 9.0],
            "close": [11.0, 11.0],
            "volume": [2.0, 2.0],
        }
    ).to_feather(path)
    with pytest.raises(ValueError, match="conflicting candles"):
        normalize_cache_file(path, "1d")


def test_cache_inspection_enforces_startup_history(tmp_path: Path) -> None:
    path = tmp_path / "BTC_USD-1d.feather"
    dates = pd.date_range("2026-01-01", periods=10, tz="UTC")
    pd.DataFrame(
        {
            "date": dates,
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 2.0,
        }
    ).to_feather(path)
    result = inspect_cache_file(
        path,
        "1d",
        backtest_start=pd.Timestamp("2026-01-10T00:00:00Z"),
        startup_candles=5,
    )
    assert result["quality_status"] == "valid"
    assert result["warmup_candles"] == 9
