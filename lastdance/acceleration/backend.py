from __future__ import annotations

import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class BenchmarkResult:
    elements: int
    baseline_runtime: float
    optimized_cpu_runtime: float
    gpu_runtime: float | None
    selected_runtime: float
    speedup: float
    selected_backend: str
    gpu_available: bool
    gpu_used: bool
    equivalent_cpu: bool
    equivalent_gpu: bool | None
    peak_memory_bytes: int
    details: dict[str, Any]


def returns_reference(prices: np.ndarray) -> np.ndarray:
    values = np.asarray(prices, dtype=np.float64)
    result = np.empty(max(len(values) - 1, 0), dtype=np.float64)
    for index in range(1, len(values)):
        result[index - 1] = values[index] / values[index - 1] - 1.0
    return result


def returns_cpu(prices: np.ndarray) -> np.ndarray:
    values = np.asarray(prices, dtype=np.float64)
    return values[1:] / values[:-1] - 1.0


def returns_gpu(prices: np.ndarray) -> np.ndarray:
    import cupy as cp

    values = cp.asarray(prices, dtype=cp.float64)
    result = values[1:] / values[:-1] - 1.0
    return cp.asnumpy(result)


def gpu_info() -> dict[str, Any]:
    try:
        import cupy as cp

        properties = cp.cuda.runtime.getDeviceProperties(0)
        return {
            "available": True,
            "cupy": cp.__version__,
            "runtime": cp.cuda.runtime.runtimeGetVersion(),
            "driver": cp.cuda.runtime.driverGetVersion(),
            "compute_capability": cp.cuda.Device().compute_capability,
            "name": properties["name"].decode()
            if isinstance(properties["name"], bytes)
            else properties["name"],
            "vram_bytes": int(properties["totalGlobalMem"]),
        }
    except Exception as exc:  # CUDA failures vary by driver/runtime combination.
        return {"available": False, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}


def _median_runtime(function: Any, values: np.ndarray, repeats: int = 3) -> tuple[float, np.ndarray]:
    timings: list[float] = []
    result: np.ndarray | None = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = function(values)
        timings.append(time.perf_counter() - started)
    assert result is not None
    return statistics.median(timings), result


def benchmark(
    mode: str = "auto", elements: int = 1_000_000, rtol: float = 1e-10, atol: float = 1e-12
) -> BenchmarkResult:
    if mode not in {"auto", "cpu", "gpu"}:
        raise ValueError("mode must be auto, cpu, or gpu")
    rng = np.random.default_rng(20260916)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.001, elements)))
    reference_size = min(elements, 250_000)
    baseline_runtime, reference_sample = _median_runtime(
        returns_reference, prices[:reference_size], repeats=1
    )
    baseline_runtime *= (elements - 1) / max(reference_size - 1, 1)
    tracemalloc.start()
    cpu_runtime, cpu_result = _median_runtime(returns_cpu, prices)
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    equivalent_cpu = bool(
        np.allclose(cpu_result[: len(reference_sample)], reference_sample, rtol=rtol, atol=atol)
    )
    info = gpu_info()
    gpu_runtime: float | None = None
    equivalent_gpu: bool | None = None
    if info.get("available"):
        try:
            returns_gpu(prices[:1000])  # warm up kernels and allocator
            gpu_runtime, gpu_result = _median_runtime(returns_gpu, prices)
            equivalent_gpu = bool(np.allclose(gpu_result, cpu_result, rtol=rtol, atol=atol))
        except Exception as exc:
            info = {**info, "available": False, "benchmark_error": f"{exc.__class__.__name__}: {exc}"}
    selected = "cpu"
    selected_runtime = cpu_runtime
    if mode == "gpu":
        if gpu_runtime is None or not equivalent_gpu:
            raise RuntimeError("GPU mode requested but unavailable or numerically non-equivalent")
        selected, selected_runtime = "gpu", gpu_runtime
    elif mode == "auto" and gpu_runtime is not None and equivalent_gpu and gpu_runtime < cpu_runtime:
        selected, selected_runtime = "gpu", gpu_runtime
    return BenchmarkResult(
        elements=elements,
        baseline_runtime=baseline_runtime,
        optimized_cpu_runtime=cpu_runtime,
        gpu_runtime=gpu_runtime,
        selected_runtime=selected_runtime,
        speedup=baseline_runtime / selected_runtime if selected_runtime else 0.0,
        selected_backend=selected,
        gpu_available=bool(info.get("available")),
        gpu_used=selected == "gpu",
        equivalent_cpu=equivalent_cpu,
        equivalent_gpu=equivalent_gpu,
        peak_memory_bytes=peak_memory,
        details=info,
    )


def benchmark_dict(**kwargs: Any) -> dict[str, Any]:
    return asdict(benchmark(**kwargs))
