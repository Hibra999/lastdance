from __future__ import annotations

import pytest

from lastdance.exchanges.freqtrade_config import (
    build_runtime_config,
    freqtrade_environment,
    write_runtime_config,
)
from lastdance.utils.secrets import redact, scan_text


def test_redaction_never_returns_complete_secret() -> None:
    value = "abcdefghijklmnop"
    result = redact(value)
    assert value not in result
    assert result.startswith("abcd") and result.endswith("mnop")


def test_secret_scanner_detects_credential_shape() -> None:
    assert scan_text("api_key=" + "abcdefghijklmnop123456")
    assert not scan_text("BITSO_API_KEY=")
    assert not scan_text("BITSO_API_KEY=\nBITSO_API_SECRET=\n")


def test_runtime_config_has_no_secrets(tmp_path) -> None:
    config = build_runtime_config(["BTC/USD"])
    assert config["dry_run"] is True
    assert config["exchange"]["key"] == ""
    write_runtime_config(tmp_path / "runtime.json", config)
    config["exchange"]["key"] = "not-allowed"
    with pytest.raises(ValueError):
        write_runtime_config(tmp_path / "unsafe.json", config)


def test_live_trading_requires_two_gates(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.delenv("LASTDANCE_LIVE_ACK", raising=False)
    with pytest.raises(RuntimeError):
        build_runtime_config(["BTC/USD"], dry_run=False)


def test_telegram_enables_only_when_both_credentials_exist(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    environment = freqtrade_environment()
    assert environment["FREQTRADE__TELEGRAM__ENABLED"] == "true"
    assert environment["FREQTRADE__TELEGRAM__TOKEN"] == "test-token"
    assert environment["FREQTRADE__TELEGRAM__CHAT_ID"] == "test-chat"
