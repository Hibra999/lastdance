from __future__ import annotations

import json
from pathlib import Path

from lastdance.reporting.consolidated import generate_report


def test_consolidated_report_generation(tmp_path: Path) -> None:
    export = tmp_path / "Example.json"
    export.write_text(
        json.dumps(
            {
                "strategy": {
                    "Example": {
                        "trades": [
                            {
                                "pair": "BTC/USD",
                                "close_date": "2026-01-02T00:00:00Z",
                                "profit_ratio": 0.02,
                            },
                            {
                                "pair": "BTC/USD",
                                "close_date": "2026-01-03T00:00:00Z",
                                "profit_ratio": -0.01,
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    metadata = {
        "timerange": "20260101-20260201",
        "data_source": "bitso",
        "outcomes": [
            {"strategy": "Example", "status": "success", "runtime_seconds": 1.2, "exports": [str(export)]}
        ],
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    output = generate_report(tmp_path, tmp_path / "report.html")
    text = output.read_text(encoding="utf-8")
    assert "Global comparison" in text
    assert "Example" in text
    assert "CAGR" in text
    assert "Exposure" in text
    assert "data:image/png;base64" in text
