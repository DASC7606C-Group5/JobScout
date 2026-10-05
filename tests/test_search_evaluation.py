"""Behavioral checks for the paired search-policy experiment and its measurements."""

import asyncio
import json
from datetime import UTC, datetime

from scripts.evaluate_search_agent import DATA, metrics, run_policy

from jobscout.schemas.conversation import MatchingReason, SourceQuoteReference
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult


def test_detail_enrichment_changes_confirmed_results_without_counting_pending_roles() -> None:
    case = next(
        row
        for row in json.loads(DATA.read_text(encoding="utf-8"))["scenarios"]
        if row["id"] == "detail_enrichment"
    )
    fixed = asyncio.run(run_policy(case, "authored-replay", "fixed"))
    adaptive = asyncio.run(run_policy(case, "authored-replay", "adaptive"))
    expected = {"j1", "j2", "j3", "j4", "j5"}
    assert fixed["returned_job_ids"] == []
    assert set(fixed["pending_job_ids"]) == expected
    assert not fixed["target_success"]
    assert set(adaptive["returned_job_ids"]) == expected
    assert adaptive["pending_job_ids"] == []
    assert adaptive["target_success"]
    assert "fetch_job_details" in {call["name"] for call in adaptive["tool_calls"]}
    assert "fetch_job_details" not in {call["name"] for call in fixed["tool_calls"]}


def test_district_evaluation_preserves_unknown_broad_locations_and_twenty_job_target() -> None:
    cases = {row["id"]: row for row in json.loads(DATA.read_text(encoding="utf-8"))["scenarios"]}
    district = asyncio.run(run_policy(cases["district_precision"], "authored-replay", "adaptive"))
    assert set(district["returned_job_ids"]) == {"j4", "j5", "j6", "j7", "j8"}
    assert (
        district["pending_job_ids"] == []
    )  # The requested five confirmed jobs fill the display limit.
    assert district["hard_condition_violations"] == {}
    twenty = asyncio.run(run_policy(cases["target_twenty"], "authored-replay", "adaptive"))
    assert set(twenty["returned_job_ids"]) == {f"j{index}" for index in range(1, 21)}
    assert twenty["target_success"]
    assert twenty["relevant_recall"] == 1


def test_measurements_detect_wrong_identity_hard_constraints_and_unsupported_citations() -> None:
    case = next(
        row
        for row in json.loads(DATA.read_text(encoding="utf-8"))["scenarios"]
        if row["id"] == "employment_exclusion"
    )
    now = datetime.now(UTC)
    job = JobPosting(
        job_id="wrong-contract",
        source="jobsdb",
        source_url="https://snapshot.example/jobs/j1",
        title="Frontend Developer",
        company="Synthetic",
        location="Hong Kong",
        target_direction="Frontend Developer",
        fetched_at=now,
        source_documents=[
            SourceDocument(
                document_id="jd",
                source="jobsdb",
                source_url="https://snapshot.example/jobs/j1",
                text="React required",
                fetched_at=now,
            )
        ],
    )
    result = RecommendationResult(
        session_id="eval",
        generated_at=now,
        jobs=[
            RecommendationItem(
                job=job,
                matching_reasons=[
                    MatchingReason(
                        requirement="React",
                        level="strong",
                        explanation="Synthetic assertion",
                        job_source_quotes=[
                            SourceQuoteReference(document_id="jd", excerpt="Invented claim")
                        ],
                        profile_source_quotes=[],
                    )
                ],
            )
        ],
    )
    measured = metrics(case, result)
    assert measured["returned_job_ids"] == ["j1"]
    assert measured["hard_condition_violations"] == {"j1": ["employment_type"]}
    assert measured["precision_at_n"] == 0
    assert measured["relevant_recall"] == 0
    assert measured["citation_count"] == 1
    assert measured["citation_correctness"] == 0
    assert not measured["target_success"]


def test_recall_excludes_relevant_roles_that_no_source_snapshot_can_return() -> None:
    case = next(
        row
        for row in json.loads(DATA.read_text(encoding="utf-8"))["scenarios"]
        if row["id"] == "source_failure"
    )
    baseline = asyncio.run(run_policy(case, "authored-replay", "adaptive"))
    case["jobs"].append({**case["jobs"][0], "id": "unreachable-role"})
    changed = asyncio.run(run_policy(case, "authored-replay", "adaptive"))
    assert set(changed["returned_job_ids"]) == set(baseline["returned_job_ids"])
    assert changed["relevant_recall"] == baseline["relevant_recall"] == 1
