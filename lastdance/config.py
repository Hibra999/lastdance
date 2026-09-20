from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from lastdance.paths import DEFAULT_APP_CONFIG, PROJECT_ROOT, resolve_project_path


class ConfigError(ValueError):
    pass


def load_yaml(path: str | Path) -> dict[str, Any]:
    resolved = resolve_project_path(path)
    if not resolved.is_file():
        raise ConfigError(f"Configuration file does not exist: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level YAML value must be a mapping: {resolved}")
    return data


def load_app_config(path: str | Path = DEFAULT_APP_CONFIG) -> dict[str, Any]:
    config = load_yaml(path)
    required = {
        "exchange": {"name", "quote_currency", "trading_mode"},
        "pairs": {"mode"},
        "strategies": {"registry", "upstream_path"},
        "backtest": {"timerange"},
        "acceleration": {"mode"},
        "trading": {"dry_run", "live_enabled"},
    }
    for section, keys in required.items():
        value = config.get(section)
        if not isinstance(value, dict):
            raise ConfigError(f"Missing mapping: {section}")
        missing = keys - value.keys()
        if missing:
            raise ConfigError(f"Missing keys in {section}: {', '.join(sorted(missing))}")
    if config["exchange"]["trading_mode"] != "spot":
        raise ConfigError("LastDance currently permits Bitso spot mode only")
    mode = config["acceleration"]["mode"]
    if mode not in {"auto", "cpu", "gpu"}:
        raise ConfigError("acceleration.mode must be auto, cpu, or gpu")
    return config


def portable_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a metadata-safe copy with project-relative paths preserved."""
    result = deepcopy(config)
    result["project_root"] = str(PROJECT_ROOT)
    return result
