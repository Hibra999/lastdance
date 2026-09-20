from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

import psutil

from lastdance.acceleration.backend import gpu_info
from lastdance.exchanges.bitso import create_exchange
from lastdance.paths import NFI_ROOT, PROJECT_ROOT
from lastdance.utils.secrets import redacted_environment


def _command_version(command: list[str]) -> dict[str, Any]:
    try:
        process = subprocess.run(command, text=True, capture_output=True, timeout=15, check=False)
        output = (process.stdout or process.stderr).strip().splitlines()
        return {"available": process.returncode == 0, "version": output[0] if output else None}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def run_doctor(*, network: bool = True) -> dict[str, Any]:
    disk = shutil.disk_usage(PROJECT_ROOT)
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "windows": os.name == "nt",
        "python": sys.version,
        "python_compatible": (3, 12) <= sys.version_info[:2] < (3, 14),
        "conda": {
            **_command_version(["conda", "--version"]),
            "active_environment": os.getenv("CONDA_DEFAULT_ENV"),
            "expected_environment": os.getenv("CONDA_DEFAULT_ENV") == "lastdance",
        },
        "git": _command_version(["git", "--version"]),
        "packages": {
            name: _package_version(name)
            for name in (
                "freqtrade",
                "ccxt",
                "quantstats",
                "TA-Lib",
                "numpy",
                "pandas",
                "scipy",
                "cupy-cuda13x",
            )
        },
        "nfi": {
            "present": (NFI_ROOT / "NostalgiaForInfinityX7.py").is_file(),
            "path": str(NFI_ROOT),
        },
        "gpu": gpu_info(),
        "cuda_toolkit": _command_version(["nvcc", "--version"]),
        "nvidia_smi": _command_version(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader",
            ]
        ),
        "cpu": {"logical_cores": os.cpu_count(), "physical_cores": psutil.cpu_count(logical=False)},
        "memory": {
            "total_bytes": psutil.virtual_memory().total,
            "available_bytes": psutil.virtual_memory().available,
        },
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
        "workspace_writable": os.access(PROJECT_ROOT, os.W_OK),
        "environment": redacted_environment(),
        "alpaca_credentials_present": bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")),
    }
    if network:
        try:
            client = create_exchange()
            report["bitso_public"] = {"reachable": True, "markets": len(client.load_markets())}
        except Exception as exc:
            report["bitso_public"] = {
                "reachable": False,
                "error": f"{exc.__class__.__name__}: {str(exc)[:160]}",
            }
    required = report["packages"]
    report["healthy"] = all(
        (
            report["windows"],
            report["python_compatible"],
            report["git"]["available"],
            report["nfi"]["present"],
            report["workspace_writable"],
            all(required[name] for name in ("freqtrade", "ccxt", "quantstats", "TA-Lib")),
            not network or report["bitso_public"]["reachable"],
        )
    )
    return report
