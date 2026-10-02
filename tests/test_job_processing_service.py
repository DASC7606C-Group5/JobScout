"""Tests for normalization, duplicate merging, and freshness status.

All inputs are fixed, self-made Mock records (plus the shared
``data/mock_jobs.json`` sample); no external service is called.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from jobscout.graph.nodes.process_jobs import process_jobs_node
from jobscout.graph.state import AgentState
from jobscout.schemas.job import FreshnessStatus
from jobscout.services.job_processing_service import process_jobs

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def make_raw(**overrides: Any) -> dict[str, Any]:
    """Build a valid raw retrieval record; override fields per test case."""
    record: dict[str, Any] = {
        "job_id": "raw-1",
        "source": "jobsdb",
        "source_url": "https://jobsdb.example.com/post/1",
        "title": "Data Analyst",
        "company": "Acme Ltd",
        "location": "Hong Kong",
        "salary": "HKD 20,000/month",
        "target_direction": "Data Analyst",
        "responsibilities": ["Build dashboards"],
        "required_skills": ["SQL", "Python"],
        "posted_at": "2026-09-20T00:00:00Z",
        "expiry_at": "2026-10-20T00:00:00Z",
        "freshness_status": "unknown",
        "fetched_at": "2026-09-28T08:00:00Z",
        "source_links": ["https://jobsdb.example.com/post/1"],
    }
    record.update(overrides)
    return record


def test_normalizes_complete_record_and_preserves_provenance() -> None:
    result = process_jobs([make_raw()], now=NOW)

    assert result.warnings == []
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_id == "raw-1"
    assert job.title == "Data Analyst"
    assert job.company == "Acme Ltd"
    assert job.location == "Hong Kong"
    assert job.salary == "HKD 20,000/month"
    assert job.target_direction == "Data Analyst"
    assert job.responsibilities == ["Build dashboards"]
    assert job.required_skills == ["SQL", "Python"]
    assert job.freshness_status is FreshnessStatus.ACTIVE  # expiry_at is in the future
    assert job.source_url == "https://jobsdb.example.com/post/1"
    assert job.source_links == ["https://jobsdb.example.com/post/1"]
    assert job.fetched_at == datetime(2026, 9, 28, 8, 0, tzinfo=UTC)

    # Serialization uses the frozen pydantic contract (no custom to_dict).
    dumped = job.model_dump(mode="json")
    assert dumped["fetched_at"] is not None
    assert datetime.fromisoformat(dumped["fetched_at"]) == job.fetched_at
    assert dumped["freshness_status"] == "active"
    assert dumped["salary"] == "HKD 20,000/month"


def test_result_supports_tuple_unpacking() -> None:
    jobs, warnings = process_jobs([make_raw()], now=NOW)

    assert len(jobs) == 1
    assert jobs[0].job_id == "raw-1"
    assert warnings == []


def test_empty_input_returns_empty_result() -> None:
    jobs, warnings = process_jobs([], now=NOW)

    assert jobs == []
    assert warnings == []


def test_whitespace_is_normalized_in_text_fields() -> None:
    result = process_jobs([make_raw(title="  Data   Analyst  ", company="\nAcme   Ltd\t")], now=NOW)

    job = result.jobs[0]
    assert job.title == "Data Analyst"
    assert job.company == "Acme Ltd"


def test_parses_responsibilities_and_skills_from_description() -> None:
    description = (
        "We are hiring.\n"
        "Responsibilities:\n"
        "- Build data pipelines\n"
        "- Maintain BI dashboards\n"
        "Requirements:\n"
        "- SQL\n"
        "- Python\n"
    )
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.responsibilities == ["Build data pipelines", "Maintain BI dashboards"]
    assert job.required_skills == ["SQL", "Python"]


def test_lexicon_fallback_when_description_has_no_skills_section() -> None:
    description = "The ideal candidate has strong Python, SQL and Tableau experience."
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.required_skills == ["Python", "SQL", "Tableau"]


@pytest.mark.parametrize(
    "field",
    ["title", "company", "source_url", "location", "target_direction", "fetched_at"],
)
def test_drops_records_missing_required_fields(field: str) -> None:
    result = process_jobs([make_raw(job_id="bad", **{field: None}), make_raw(job_id="ok")], now=NOW)

    assert [job.job_id for job in result.jobs] == ["ok"]
    assert any("bad" in warning and field in warning for warning in result.warnings)


def test_drops_record_with_unparseable_fetched_at() -> None:
    result = process_jobs([make_raw(job_id="bad", fetched_at="not-a-date")], now=NOW)

    assert result.jobs == []
    assert any("bad" in warning and "fetched_at" in warning for warning in result.warnings)


def test_missing_optional_fields_keep_job_with_warnings() -> None:
    record = make_raw(salary=None, posted_at=None, expiry_at=None)

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.salary is None
    assert job.posted_at is None
    assert job.expiry_at is None
    assert any("missing salary" in warning for warning in result.warnings)
    assert any("missing posted_at" in warning for warning in result.warnings)
    assert any("missing expiry_at" in warning for warning in result.warnings)


def test_missing_source_falls_back_to_unknown_with_warning() -> None:
    result = process_jobs([make_raw(source=None)], now=NOW)

    job = result.jobs[0]
    assert job.source == "unknown"
    assert any("missing source" in warning for warning in result.warnings)


def test_warns_when_no_responsibilities_or_skills_extracted() -> None:
    record = make_raw(responsibilities=[], required_skills=[])

    result = process_jobs([record], now=NOW)

    job = result.jobs[0]
    assert job.responsibilities == []
    assert job.required_skills == []
    assert any("no responsibilities or required skills" in warning for warning in result.warnings)


def test_merges_cross_source_duplicates_and_keeps_all_links() -> None:
    first = make_raw(
        job_id="a",
        source="jobsdb",
        source_url="https://jobsdb.example.com/post/1",
        source_links=["https://jobsdb.example.com/post/1"],
        required_skills=["SQL"],
        fetched_at="2026-09-27T08:00:00Z",
    )
    second = make_raw(
        job_id="b",
        source="linkedin",
        source_url="https://linkedin.example.com/jobs/99",
        source_links=["https://linkedin.example.com/jobs/99"],
        required_skills=["Python", "sql"],
        fetched_at="2026-09-28T09:00:00Z",
    )

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "jobsdb, linkedin"
    assert job.source_links == [
        "https://jobsdb.example.com/post/1",
        "https://linkedin.example.com/jobs/99",
    ]
    assert job.required_skills == ["SQL", "Python"]
    assert job.fetched_at == datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def test_dedup_key_ignores_case_and_punctuation() -> None:
    first = make_raw(job_id="a", company="Acme, Ltd.", title="Data Analyst!")
    second = make_raw(job_id="b", company="acme ltd", title="data analyst")

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1


def test_does_not_merge_different_locations_or_titles() -> None:
    other_location = make_raw(job_id="b", location="Singapore")
    other_title = make_raw(job_id="c", title="Data Engineer")

    result = process_jobs([make_raw(job_id="a"), other_location, other_title], now=NOW)

    assert len(result.jobs) == 3


def test_freshness_expired_when_expiry_passed() -> None:
    job = process_jobs([make_raw(expiry_at="2026-09-01T00:00:00Z")], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


def test_freshness_active_when_expiry_in_future() -> None:
    job = process_jobs([make_raw(expiry_at="2026-12-31T00:00:00Z")], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.ACTIVE


def test_freshness_honors_explicit_source_status_case_insensitively() -> None:
    record = make_raw(expiry_at=None, freshness_status="Expired")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


def test_freshness_unknown_without_evidence() -> None:
    record = make_raw(expiry_at=None, freshness_status=None)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.UNKNOWN


def test_posted_at_alone_never_proves_active() -> None:
    record = make_raw(expiry_at=None, freshness_status=None, posted_at="2020-01-01T00:00:00Z")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.UNKNOWN


def test_expiry_beats_explicit_active_status() -> None:
    record = make_raw(expiry_at="2026-09-01T00:00:00Z", freshness_status="active")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


def test_generates_stable_job_id_when_missing() -> None:
    first = process_jobs([make_raw(job_id=None)], now=NOW).jobs[0]
    second = process_jobs([make_raw(job_id=None)], now=NOW).jobs[0]

    assert first.job_id.startswith("gen-")
    assert first.job_id == second.job_id


def test_shared_mock_sample_stays_unknown_and_keeps_provenance() -> None:
    raw_jobs: list[dict[str, Any]] = json.loads((DATA_DIR / "mock_jobs.json").read_text("utf-8"))

    result = process_jobs(raw_jobs, now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.freshness_status is FreshnessStatus.UNKNOWN  # never faked as active
    assert job.source_url == "https://example.com/jobs/mock-001"
    assert job.source_links == ["https://example.com/jobs/mock-001"]
    assert job.fetched_at == datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    assert job.required_skills == ["SQL", "Python"]
    # Optional fields the sample lacks stay None and are reported, not fabricated.
    assert job.salary is None
    assert job.posted_at is None
    assert job.expiry_at is None
    assert any("missing salary" in warning for warning in result.warnings)
    assert any("missing posted_at" in warning for warning in result.warnings)
    assert any("missing expiry_at" in warning for warning in result.warnings)


def test_node_reads_raw_jobs_and_writes_state_update() -> None:
    state: AgentState = {"session_id": "test-session", "raw_jobs": [make_raw()]}

    update = process_jobs_node(state)

    assert len(update["normalized_jobs"]) == 1
    assert update["normalized_jobs"][0].title == "Data Analyst"
    assert update["warnings"] == []
    assert update["errors"] == []
    assert update["current_stage"] == "process_jobs"


def test_node_handles_missing_raw_jobs_key() -> None:
    state: AgentState = {"session_id": "test-session"}

    update = process_jobs_node(state)

    assert update["normalized_jobs"] == []
    assert update["warnings"] == []
    assert update["current_stage"] == "failed"
    assert [error.code for error in update["errors"]] == ["RAW_JOBS_MISSING"]


def test_node_handles_empty_raw_jobs() -> None:
    state: AgentState = {"session_id": "test-session", "raw_jobs": []}

    update = process_jobs_node(state)

    assert update["normalized_jobs"] == []
    assert update["warnings"] == []
    assert update["errors"] == []
    assert update["current_stage"] == "process_jobs"


def test_node_rejects_invalid_raw_jobs() -> None:
    state = cast(AgentState, {"session_id": "test-session", "raw_jobs": "not-a-list"})

    update = process_jobs_node(state)

    assert update["current_stage"] == "failed"
    assert [error.code for error in update["errors"]] == ["RAW_JOBS_INVALID"]
