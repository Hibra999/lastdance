from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    rows: int
    first_candle: str | None
    last_candle: str | None
    duplicate_timestamps: int
    missing_values: int
    invalid_ohlc_rows: int
    nonpositive_volume_rows: int


def normalize_ohlcv(rows: list[list[Any]], *, timestamp_unit: str = "ms") -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit=timestamp_unit, utc=True)
    for column in OHLCV_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)


def validate_ohlcv(frame: pd.DataFrame) -> ValidationResult:
    if frame.empty:
        return ValidationResult(False, 0, None, None, 0, 0, 0, 0)
    duplicate_timestamps = int(frame["timestamp"].duplicated().sum())
    missing_values = int(frame[OHLCV_COLUMNS].isna().sum().sum())
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    nonpositive_volume = int((frame["volume"] < 0).sum())
    invalid_count = int(invalid.sum())
    return ValidationResult(
        valid=duplicate_timestamps == 0
        and missing_values == 0
        and invalid_count == 0
        and nonpositive_volume == 0,
        rows=len(frame),
        first_candle=frame["timestamp"].iloc[0].isoformat(),
        last_candle=frame["timestamp"].iloc[-1].isoformat(),
        duplicate_timestamps=duplicate_timestamps,
        missing_values=missing_values,
        invalid_ohlc_rows=invalid_count,
        nonpositive_volume_rows=nonpositive_volume,
    )
