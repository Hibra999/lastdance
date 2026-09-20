from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request

from lastdance.paths import NFI_ROOT, PROJECT_ROOT


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=check)


def latest_release() -> dict[str, str]:
    request = urllib.request.Request(
        "https://api.github.com/repos/iterativv/NostalgiaForInfinity/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "LastDance-Updater"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return {"tag": payload["tag_name"], "published_at": payload["published_at"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or safely apply an NFI release")
    parser.add_argument(
        "--apply", action="store_true", help="Checkout the latest release and run compatibility tests"
    )
    args = parser.parse_args()
    current_tag = run(
        "git", "-C", str(NFI_ROOT), "describe", "--tags", "--exact-match", check=False
    ).stdout.strip()
    current_commit = run("git", "-C", str(NFI_ROOT), "rev-parse", "HEAD").stdout.strip()
    latest = latest_release()
    print(
        json.dumps({"current_tag": current_tag, "current_commit": current_commit, "latest": latest}, indent=2)
    )
    if latest["tag"] == current_tag or not args.apply:
        return 0
    run("git", "-C", str(NFI_ROOT), "fetch", "--tags", "origin")
    checkout = run("git", "-C", str(NFI_ROOT), "checkout", latest["tag"], check=False)
    if checkout.returncode:
        print(checkout.stderr, file=sys.stderr)
        return checkout.returncode
    tests = run(sys.executable, "-m", "pytest", "tests/test_strategies.py", check=False)
    if tests.returncode:
        run("git", "-C", str(NFI_ROOT), "checkout", current_commit)
        print("Update rolled back because compatibility tests failed.", file=sys.stderr)
        print(tests.stdout, tests.stderr, file=sys.stderr)
        return tests.returncode
    print("NFI checkout updated. Review the diff and update pinned metadata before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
