from __future__ import annotations

from lastdance.data.normalize import normalize_ohlcv, validate_ohlcv


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
