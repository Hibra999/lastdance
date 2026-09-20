from __future__ import annotations

import pytest

from lastdance.cli.main import build_parser, main


def test_cli_exposes_required_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    for command in (
        "doctor",
        "pairs",
        "data",
        "strategies",
        "backtest",
        "report",
        "verify-bitso",
        "dry-run",
        "all",
    ):
        assert command in help_text


def test_doctor_without_network(capsys) -> None:
    result = main(["doctor", "--no-network"])
    assert result == 0
    assert '"healthy": true' in capsys.readouterr().out


def test_parser_rejects_missing_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
