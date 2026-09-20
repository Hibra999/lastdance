from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from lastdance.data.normalize import cache_file, normalize_cache_file, timeframe_delta
from lastdance.exchanges.freqtrade_config import freqtrade_environment
from lastdance.paths import PROJECT_ROOT, USER_DATA_DIR


def run_freqtrade(
    command: list[str], *, log_path: Path | None = None, timeout: int | None = None
) -> dict[str, Any]:
    full_command = [sys.executable, "-m", "freqtrade", *command]
    started = datetime.now(UTC)
    process = subprocess.run(
        full_command,
        cwd=PROJECT_ROOT,
        env=freqtrade_environment(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = f"{process.stdout}\n{process.stderr}".strip()
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output + "\n", encoding="utf-8")
    return {
        "command": command,
        "returncode": process.returncode,
        "runtime_seconds": (datetime.now(UTC) - started).total_seconds(),
        "output": output,
    }


def download_bitso_data(
    runtime_config: Path,
    pairs: list[str],
    timeframes: list[str],
    timerange: str,
    *,
    startup_candles: int = 800,
    log_path: Path | None = None,
) -> dict[str, Any]:
    data_dir = USER_DATA_DIR / "data"
    started = datetime.now(UTC)
    commands: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    start_text, separator, end_text = timerange.partition("-")
    if not separator or len(start_text) != 8:
        raise ValueError(f"Unsupported timerange: {timerange}")
    backtest_start = pd.Timestamp(datetime.strptime(start_text, "%Y%m%d"), tz="UTC")

    def warm_start(timeframe: str) -> pd.Timestamp:
        return (backtest_start - (startup_candles + 2) * timeframe_delta(timeframe)).floor("D")

    def invoke(timeframe: str, selected_pairs: list[str], *, prepend: bool) -> bool:
        if not selected_pairs:
            return True
        expanded = f"{warm_start(timeframe):%Y%m%d}-{end_text}"
        command = [
            "download-data",
            "--config",
            str(runtime_config),
            "--datadir",
            str(data_dir),
            "--trading-mode",
            "spot",
            "--timerange",
            expanded,
            "--timeframes",
            timeframe,
            "--pairs",
            *selected_pairs,
        ]
        if prepend:
            command.append("--prepend")
        result: dict[str, Any] | None = None
        for _ in range(2):
            result = run_freqtrade(command)
            commands.append(result)
            if result["returncode"] == 0:
                break
        assert result is not None
        stages.append(
            {
                "timeframe": timeframe,
                "mode": "prepend" if prepend else "update",
                "pairs": selected_pairs,
                "returncode": result["returncode"],
            }
        )
        return result["returncode"] == 0

    for timeframe in timeframes:
        existing: list[str] = []
        missing: list[str] = []
        for pair in pairs:
            path = cache_file(data_dir, pair, timeframe)
            if path.is_file():
                normalized.append(normalize_cache_file(path, timeframe))
                first = pd.read_feather(path, columns=["date"])["date"].min()
                if pd.isna(first) or pd.Timestamp(first) > warm_start(timeframe):
                    existing.append(pair)
            else:
                missing.append(pair)
        prepared = invoke(timeframe, existing, prepend=True)
        prepared = invoke(timeframe, missing, prepend=False) and prepared
        if prepared:
            invoke(timeframe, pairs, prepend=False)
        for pair in pairs:
            path = cache_file(data_dir, pair, timeframe)
            if path.is_file():
                normalized.append(normalize_cache_file(path, timeframe))

    output = "\n\n".join(item["output"] for item in commands)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output + "\n", encoding="utf-8")
    return {
        "command_count": len(commands),
        "commands": [item["command"] for item in commands],
        "stages": stages,
        "returncode": max((item["returncode"] for item in stages), default=0),
        "runtime_seconds": (datetime.now(UTC) - started).total_seconds(),
        "normalization": normalized,
        "output_tail": output[-4000:],
    }
