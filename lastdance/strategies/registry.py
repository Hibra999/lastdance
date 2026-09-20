from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lastdance.config import load_yaml
from lastdance.paths import DEFAULT_STRATEGY_REGISTRY, resolve_project_path


@dataclass(frozen=True)
class StrategySpec:
    name: str
    enabled: bool
    source: Path
    compatibility: str
    timeframe: str
    startup_candles: int
    metadata: dict[str, Any]


class StrategyRegistry:
    def __init__(self, path: str | Path = DEFAULT_STRATEGY_REGISTRY) -> None:
        self.path = resolve_project_path(path)
        payload = load_yaml(self.path)
        self.upstream = payload.get("upstream", {})
        raw = payload.get("strategies", {})
        if not isinstance(raw, dict):
            raise ValueError("strategies must be a mapping")
        self._strategies: dict[str, StrategySpec] = {}
        for name, metadata in raw.items():
            if not isinstance(metadata, dict):
                raise ValueError(f"Strategy metadata must be a mapping: {name}")
            source = resolve_project_path(metadata["source"])
            self._strategies[name] = StrategySpec(
                name=name,
                enabled=bool(metadata.get("enabled", False)),
                source=source,
                compatibility=str(metadata.get("compatibility", "unknown")),
                timeframe=str(metadata.get("timeframe", "5m")),
                startup_candles=int(metadata.get("startup_candles", 0)),
                metadata=dict(metadata),
            )

    def all(self) -> list[StrategySpec]:
        return list(self._strategies.values())

    def enabled(self) -> list[StrategySpec]:
        return [item for item in self.all() if item.enabled]

    def get(self, name: str) -> StrategySpec:
        try:
            return self._strategies[name]
        except KeyError as exc:
            raise KeyError(f"Unknown strategy: {name}") from exc

    def validate_sources(self) -> dict[str, str]:
        return {item.name: "present" if item.source.is_file() else "missing" for item in self.all()}
