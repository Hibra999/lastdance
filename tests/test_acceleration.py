from __future__ import annotations

import numpy as np
import pytest

from lastdance.acceleration.backend import benchmark, returns_cpu, returns_gpu, returns_reference


def test_cpu_implementation_matches_reference() -> None:
    prices = np.array([100.0, 101.0, 99.0, 102.0])
    np.testing.assert_allclose(returns_cpu(prices), returns_reference(prices), rtol=1e-14, atol=1e-14)


def test_gpu_implementation_matches_cpu_when_available() -> None:
    prices = np.linspace(90.0, 110.0, 10_000)
    np.testing.assert_allclose(returns_gpu(prices), returns_cpu(prices), rtol=1e-12, atol=1e-12)


@pytest.mark.slow
def test_benchmark_records_baseline_and_selection() -> None:
    result = benchmark(elements=100_000)
    assert result.baseline_runtime > 0
    assert result.optimized_cpu_runtime > 0
    assert result.equivalent_cpu
    assert result.equivalent_gpu is not False
    assert result.selected_backend in {"cpu", "gpu"}
