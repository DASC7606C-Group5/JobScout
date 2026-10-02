"""CLI contract and error exit codes, entirely offline."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "sample, count",
    [("unrestricted.json", 6), ("hong_kong_internships.json", 2), ("source_coverage.json", 7)],
)
def test_mock_demo_files(tmp_path: Path, sample: str, count: int) -> None:
    output = tmp_path / "output.json"
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/demo_job_search.py"),
            "--mode",
            "mock",
            "--input",
            str(ROOT / "data/group4" / sample),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["mode"] == "mock" and data["returned_count"] == count and not data["errors"]
    assert data["warnings"] and data["outcomes"]


def test_invalid_input_is_structured_and_does_not_echo_private_text(tmp_path: Path) -> None:
    file = tmp_path / "bad.json"
    file.write_text('{"private_resume": "SECRET"}', encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/demo_job_search.py"),
            "--mode",
            "mock",
            "--input",
            str(file),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 2 and "SECRET" not in run.stdout + run.stderr
    assert json.loads(run.stdout)["errors"][0]["code"] == "SEARCH_INPUT"
