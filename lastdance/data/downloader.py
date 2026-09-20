from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    log_path: Path | None = None,
) -> dict[str, Any]:
    command = [
        "download-data",
        "--config",
        str(runtime_config),
        "--datadir",
        str(USER_DATA_DIR / "data"),
        "--trading-mode",
        "spot",
        "--timerange",
        timerange,
        "--timeframes",
        *timeframes,
        "--pairs",
        *pairs,
    ]
    return run_freqtrade(command, log_path=log_path)
