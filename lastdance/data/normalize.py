from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def cache_file(data_dir: Path, pair: str, timeframe: str) -> Path:
    stem = pair.replace("/", "_").replace(":", "_")
    return data_dir / f"{stem}-{timeframe}.feather"


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


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    units = {"m": "min", "h": "h", "d": "D", "w": "W"}
    try:
        return pd.Timedelta(int(timeframe[:-1]), unit=units[timeframe[-1]])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def normalize_cache_file(path: Path, timeframe: str) -> dict[str, Any]:
    """Canonicalize a Freqtrade feather file without inventing market data."""
    frame = pd.read_feather(path)
    if frame.empty:
        return {"path": str(path), "rows_before": 0, "rows_after": 0, "merged_duplicates": 0}
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    canonical = frame["date"].dt.floor(timeframe_delta(timeframe))
    values = [column for column in ("open", "high", "low", "close", "volume") if column in frame]
    conflicts = 0
    for _, duplicate in frame.assign(_canonical=canonical).groupby("_canonical", dropna=False):
        if len(duplicate) > 1 and any(duplicate[column].nunique(dropna=False) > 1 for column in values):
            conflicts += 1
    if conflicts:
        raise ValueError(f"{path.name}: {conflicts} conflicting candles collapse to the same {timeframe} bucket")
    rows_before = len(frame)
    frame["date"] = canonical
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    frame.to_feather(path)
    return {
        "path": str(path),
        "rows_before": rows_before,
        "rows_after": len(frame),
        "merged_duplicates": rows_before - len(frame),
    }


def inspect_cache_file(
    path: Path,
    timeframe: str,
    *,
    backtest_start: pd.Timestamp | None = None,
    startup_candles: int = 0,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": str(path),
        "timeframe": timeframe,
        "candles": 0,
        "first_candle": None,
        "last_candle": None,
        "sha256": None,
        "duplicate_timestamps": 0,
        "misaligned_timestamps": 0,
        "missing_values": 0,
        "invalid_ohlc_rows": 0,
        "gap_count": 0,
        "max_gap_candles": 0,
        "warmup_candles": 0,
        "required_warmup_candles": startup_candles,
        "required_start": None,
        "warmup_ok": False,
        "quality_status": "invalid",
        "issues": [],
    }
    if not path.is_file():
        item["issues"].append("missing_file")
        return item
    item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = pd.read_feather(path)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        item["issues"].append("missing_columns")
        return item
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    delta = timeframe_delta(timeframe)
    item["candles"] = len(frame)
    if frame.empty:
        item["issues"].append("empty_file")
        return item
    item["first_candle"] = frame["date"].min().isoformat()
    item["last_candle"] = frame["date"].max().isoformat()
    item["duplicate_timestamps"] = int(frame["date"].duplicated().sum())
    item["misaligned_timestamps"] = int((frame["date"] != frame["date"].dt.floor(delta)).sum())
    item["missing_values"] = int(frame[list(required)].isna().sum().sum())
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["volume"] < 0)
    )
    item["invalid_ohlc_rows"] = int(invalid.sum())
    ordered = frame["date"].sort_values().dropna()
    gaps = ordered.diff().dropna()
    item["gap_count"] = int((gaps > delta).sum())
    if not gaps.empty:
        item["max_gap_candles"] = max(0, int(gaps.max() / delta) - 1)
        if gaps.max() > pd.Timedelta(days=7):
            item["issues"].append("gap_over_7_days")
    if backtest_start is None:
        item["warmup_ok"] = True
    else:
        start = pd.Timestamp(backtest_start)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
        required_start = start - startup_candles * delta
        item["required_start"] = required_start.isoformat()
        item["warmup_candles"] = int((ordered < start).sum())
        item["warmup_ok"] = bool(
            not ordered.empty
            and item["warmup_candles"] >= startup_candles
            and ordered.iloc[0] <= required_start
        )
    for field, issue in (
        ("duplicate_timestamps", "duplicate_timestamps"),
        ("misaligned_timestamps", "misaligned_timestamps"),
        ("missing_values", "missing_values"),
        ("invalid_ohlc_rows", "invalid_ohlc"),
    ):
        if item[field]:
            item["issues"].append(issue)
    if not item["warmup_ok"]:
        item["issues"].append("insufficient_warmup")
    item["quality_status"] = "valid" if not item["issues"] else "invalid"
    return item
