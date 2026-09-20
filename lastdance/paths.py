from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_CONFIG = PROJECT_ROOT / "config" / "app.yaml"
DEFAULT_STRATEGY_REGISTRY = PROJECT_ROOT / "config" / "strategies.yaml"
DEFAULT_FREQTRADE_CONFIG = PROJECT_ROOT / "config" / "freqtrade" / "base.json"
NFI_ROOT = PROJECT_ROOT / "third_party" / "NostalgiaForInfinity"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORTS_DIR = PROJECT_ROOT / "reports"
USER_DATA_DIR = PROJECT_ROOT / "user_data"


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path
