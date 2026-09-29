"""Run the project's local checks with the active Python environment."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    ("Lint", ("ruff", "check", ".")),
    ("Formatting", ("ruff", "format", "--check", ".")),
    ("Types", ("mypy",)),
    ("Tests", ("pytest",)),
)


def main() -> int:
    failed: list[str] = []
    for label, command in CHECKS:
        print(f"\nRunning {label.lower()}...", flush=True)
        result = subprocess.run([sys.executable, "-m", *command], cwd=ROOT, check=False)
        if result.returncode != 0:
            failed.append(label)

    if failed:
        print(f"\nFailed: {', '.join(failed)}", flush=True)
        return 1

    print("\nAll checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
