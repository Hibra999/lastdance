from __future__ import annotations

from pathlib import Path

import pytest

from lastdance.config import ConfigError, load_app_config, load_yaml


def test_default_config_is_safe() -> None:
    config = load_app_config()
    assert config["exchange"]["name"] == "bitso"
    assert config["exchange"]["trading_mode"] == "spot"
    assert config["trading"] == {
        "dry_run": True,
        "live_enabled": False,
        "require_environment_gate": True,
    }


def test_invalid_config_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("exchange: bitso\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_app_config(path)


def test_yaml_requires_mapping(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml(path)
