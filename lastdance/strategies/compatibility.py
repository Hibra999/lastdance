from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from lastdance.strategies.registry import StrategyRegistry


def inspect_strategy_source(path: Path, expected_class: str) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    return {
        "path": str(path),
        "syntax_valid": True,
        "class_present": expected_class in classes,
        "classes": classes,
    }


def inspect_registry(registry: StrategyRegistry) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in registry.all():
        try:
            result = inspect_strategy_source(spec.source, spec.name)
            result.update({"name": spec.name, "enabled": spec.enabled, "compatibility": spec.compatibility})
        except (OSError, SyntaxError) as exc:
            result = {"name": spec.name, "path": str(spec.source), "syntax_valid": False, "error": str(exc)}
        results.append(result)
    return results
