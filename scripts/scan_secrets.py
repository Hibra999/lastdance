from __future__ import annotations

import subprocess
from pathlib import Path

from lastdance.paths import PROJECT_ROOT
from lastdance.utils.secrets import scan_paths


def tracked_files() -> list[Path]:
    process = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return [
        PROJECT_ROOT / value
        for value in process.stdout.splitlines()
        if value and not value.startswith("third_party/")
    ]


if __name__ == "__main__":
    findings = scan_paths(tracked_files())
    if findings:
        for path in findings:
            print(f"Potential secret: {path}")
        raise SystemExit(1)
    print("Secret scan passed: no credential-like values detected.")
