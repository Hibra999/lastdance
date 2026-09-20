from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

SECRET_NAMES = (
    "BITSO_API_KEY",
    "BITSO_API_SECRET",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)

SUSPICIOUS_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret|bot[_-]?token)[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9_\-]{16,}"
    ),
    re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
)


def redact(value: str | None, visible: int = 4) -> str:
    if not value:
        return "<not set>"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * 8}{value[-visible:]}"


def redacted_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = environ or os.environ
    return {name: redact(source.get(name)) for name in SECRET_NAMES}


def scan_text(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def scan_paths(paths: list[Path]) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    for path in paths:
        try:
            matches = scan_text(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if matches:
            findings[str(path)] = matches
    return findings
