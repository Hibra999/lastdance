from __future__ import annotations

import importlib.util
import sys

import pytest

from lastdance.strategies.compatibility import inspect_registry
from lastdance.strategies.registry import StrategyRegistry
from lastdance.strategies.runtime_patch import prepare_strategy_path


def test_registry_enabled_strategies() -> None:
    registry = StrategyRegistry()
    assert [item.timeframe for item in registry.enabled()] == ["5m"] * 8
    assert registry.get("NostalgiaForInfinityNextGen").enabled is False
    assert all(status == "present" for status in registry.validate_sources().values())


def test_all_registered_sources_have_expected_class() -> None:
    results = inspect_registry(StrategyRegistry())
    assert results
    assert all(item["syntax_valid"] and item["class_present"] for item in results)


@pytest.mark.parametrize("name", [item.name for item in StrategyRegistry().enabled()])
def test_enabled_nfi_strategy_imports(name: str) -> None:
    source = StrategyRegistry().get(name).source
    spec = importlib.util.spec_from_file_location(f"lastdance_test_{name}", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        strategy = getattr(module, name)
        assert strategy.INTERFACE_VERSION in {2, 3}
        assert strategy.timeframe == "5m"
        assert strategy.startup_candle_count in {480, 800}
    finally:
        sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("name", ["NostalgiaForInfinityX5", "NostalgiaForInfinityNext"])
def test_runtime_compatibility_patch_keeps_upstream_source_unchanged(name: str) -> None:
    source = StrategyRegistry().get(name).source
    before = source.read_bytes()
    runtime_source = prepare_strategy_path(name, source) / source.name
    assert runtime_source.is_file()
    assert runtime_source.read_bytes() != before
    assert source.read_bytes() == before
