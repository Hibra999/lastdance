import json

from lastdance.doctor import run_doctor

if __name__ == "__main__":
    report = run_doctor()
    print(json.dumps(report, indent=2, default=str))
    raise SystemExit(0 if report["healthy"] else 1)
