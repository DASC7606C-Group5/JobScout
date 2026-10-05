"""CLI contract and error exit codes, entirely offline."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "sample, expected",
    [
        (
            "unrestricted.json",
            {
                (source, direction, identity)
                for source in ("zhaopin", "liepin", "jobsdb")
                for direction, identities in (
                    ("Data Analyst", ("10", "11")),
                    ("Business Analyst", ("20", "21")),
                )
                for identity in identities
            },
        ),
        (
            "hong_kong_internships.json",
            {
                ("jobsdb", "Data Analyst", "10"),
                ("jobsdb", "Data Analyst", "11"),
                ("jobsdb", "Business Analyst", "20"),
                ("jobsdb", "Business Analyst", "21"),
            },
        ),
        (
            "source_coverage.json",
            {
                (source, direction, identity)
                for source in ("zhaopin", "liepin")
                for direction, identities in (
                    ("Data Analyst", ("10", "11")),
                    ("Business Analyst", ("20", "21")),
                )
                for identity in identities
            }
            | {
                ("shixiseng", "Data Analyst", "inn_1"),
                ("shixiseng", "Business Analyst", "inn_2"),
                ("jobsdb", "Data Analyst", "10"),
                ("jobsdb", "Data Analyst", "11"),
            },
        ),
    ],
)
def test_mock_demo_files(tmp_path: Path, sample: str, expected: set[tuple[str, str, str]]) -> None:
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
    assert data["mode"] == "mock" and not data["errors"]
    assert {
        (job["source"], job["target_direction"], job["source_job_id"]) for job in data["raw_jobs"]
    } == expected
    assert data["returned_count"] == len(data["raw_jobs"]) == len(expected)
    for request in data["requests"]:
        if not request["location_unrestricted"]:
            assert request["location_ref"]["id"] == (
                "hk" if request["location"] == "Hong Kong" else "cn:538"
            )
    assert data["warnings"] and data["outcomes"]


def test_demo_rebinds_untrusted_native_codes_and_rejects_unknown_places(tmp_path: Path) -> None:
    file = tmp_path / "requests.json"
    file.write_text(
        json.dumps(
            [
                {
                    "target_direction": "Data Analyst",
                    "location": "Shanghai",
                    "employment_type": "internship",
                    "sources": ["zhaopin"],
                    "location_ref": {
                        "id": "fabricated",
                        "name": "Shanghai",
                        "region": "cn",
                        "level": "city",
                        "source_codes": {"zhaopin": "forged"},
                    },
                },
                {
                    "target_direction": "Data Analyst",
                    "location": "Unknown District",
                    "employment_type": "internship",
                },
            ]
        ),
        encoding="utf-8",
    )
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
    assert run.returncode == 1
    output = json.loads(run.stdout)
    assert output["requests"][0]["location_ref"]["id"] == "cn:538"
    assert output["requests"][0]["location_ref"]["source_codes"]["zhaopin"] == "538"
    assert [error["code"] for error in output["errors"]] == ["SEARCH_LOCATION_UNSUPPORTED"]
    assert {job["source_job_id"] for job in output["raw_jobs"]} == {"10", "11"}


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
