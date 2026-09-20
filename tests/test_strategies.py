from __future__ import annotations

import importlib.util
import sys

import pytest

from lastdance.strategies.compatibility import inspect_registry
from lastdance.strategies.registry import StrategyRegistry


def test_registry_enabled_strategies() -> None:
    registry = StrategyRegistry()
    assert [item.name for item in registry.enabled()] == ["NostalgiaForInfinityX7", "NostalgiaForInfinityX6"]
    assert all(status == "present" for status in registry.validate_sources().values())


def test_all_registered_sources_have_expected_class() -> None:
    results = inspect_registry(StrategyRegistry())
    assert results
    assert all(item["syntax_valid"] and item["class_present"] for item in results)


@pytest.mark.parametrize("name", ["NostalgiaForInfinityX7", "NostalgiaForInfinityX6"])
def test_enabled_nfi_strategy_imports(name: str) -> None:
    source = StrategyRegistry().get(name).source
    spec = importlib.util.spec_from_file_location(f"lastdance_test_{name}", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        strategy = getattr(module, name)
        assert strategy.INTERFACE_VERSION == 3
        assert strategy.timeframe == "5m"
        assert strategy.startup_candle_count == 800
    finally:
        sys.modules.pop(spec.name, None)
