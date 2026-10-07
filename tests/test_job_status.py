"""Job status reasons distinguish service failures, evidence and search conditions."""

import asyncio
from typing import Any

import pytest

from jobscout.schemas.job_status import ReviewIssue
from jobscout.services.job_assessment_service import JobAssessmentService
from jobscout.services.llm_service import ModelServiceError
from jobscout.services.recommendation_service import eligibility_exclusions
from tests.test_job_assessment_service import (
    PROFILE_DOCUMENTS,
    ReplayProvider,
    assess,
    job,
    profile,
)
from tests.test_recommendation_service import job as candidate
from tests.test_recommendation_service import profile as search_profile


@pytest.mark.parametrize("stage", ["jd_analysis", "matching"])
@pytest.mark.parametrize(
    ("error", "reason", "status"),
    [
        ("model_timeout", "timeout", "timeout"),
        ("model_transport", "service_unavailable", "unavailable"),
        ("model_auth", "service_unavailable", "unavailable"),
        ("model_output", "invalid_output", "invalid"),
        ("model_input", "failed", "failed"),
    ],
)
def test_model_failures_preserve_the_job_and_public_failure_reason(
    stage: str, error: str, reason: str, status: str
) -> None:
    def fail(task: str, response: dict[str, Any]) -> None:
        if task == stage:
            raise ModelServiceError(error)

    original = job("failure")
    result = assess(ReplayProvider(fail), [original])
    item = [*result.jobs, *result.pending_jobs][0]
    assert item.job.job_id == original.job_id
    assert item.job.description == original.description
    assert item.review_issue is not None
    assert item.review_issue.model_dump() == {"code": reason, "stage": stage}
    assert item.display_status(active=False) == status


def test_invalid_evidence_and_missing_job_information_have_different_reasons() -> None:
    def invalid(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            response["jobs"][0]["matches"][0]["profile_source_quotes"][0]["excerpt"] = "Invented"

    broken = assess(ReplayProvider(invalid), [job("invalid")]).jobs[0]
    assert broken.display_status(active=False) == "invalid"
    assert broken.review_issue == ReviewIssue(code="invalid_evidence", stage="matching")

    def empty(task: str, response: dict[str, Any]) -> None:
        if task == "jd_analysis":
            response["jobs"][0]["requirements"] = []

    missing = assess(ReplayProvider(empty), [job("missing")]).jobs[0]
    assert missing.display_status(active=False) == "insufficient"
    assert missing.review_issue == ReviewIssue(
        code="insufficient_job_information", stage="jd_analysis"
    )


def test_retry_replaces_failure_with_a_completed_assessment() -> None:
    attempts = 0

    def first_failure(task: str, response: dict[str, Any]) -> None:
        nonlocal attempts
        if task == "matching":
            attempts += 1
            if attempts == 1:
                raise ModelServiceError("model_timeout")

    async def scenario() -> None:
        service = JobAssessmentService(ReplayProvider(first_failure))
        await service.begin_search("confirmed")
        first = await service.assess(profile(), [job("retry")], PROFILE_DOCUMENTS, "s")
        assert first.jobs[0].display_status(active=False) == "timeout"
        second = await service.assess(profile(), [job("retry")], PROFILE_DOCUMENTS, "s")
        assert second.jobs[0].display_status(active=False) == "reviewed"
        assert second.jobs[0].review_issue is None
        assert second.jobs[0].matching_reasons[0].level == "strong"

    asyncio.run(scenario())


def test_exclusion_reasons_keep_duplicates_expiry_and_conditions_distinct() -> None:
    original = candidate("a")
    excluded = eligibility_exclusions(
        search_profile(),
        [
            original,
            candidate("duplicate", source_url=original.source_url),
            candidate("expired", freshness_status="expired"),
            candidate("role", target_direction="Sales"),
            candidate("employment", employment_type="full-time"),
            candidate("unknown", location="Unknown", employment_type=None),
        ],
    )
    assert excluded == {
        "duplicate": ["duplicate"],
        "expired": ["expired"],
        "role": ["role"],
        "employment": ["employment_type"],
    }


def test_model_condition_conflicts_report_the_actual_condition() -> None:
    def conflict(task: str, response: dict[str, Any]) -> None:
        if task == "jd_analysis":
            response["jobs"][0]["direction"] = "mismatch"

    async def scenario() -> None:
        service = JobAssessmentService(ReplayProvider(conflict))
        await service.begin_search("confirmed")
        result = await service.assess(profile(), [job("role")], PROFILE_DOCUMENTS, "s")
        assert not result.jobs and not result.pending_jobs
        assert service.diagnostics["role"].exclusion_reasons == ["role"]

    asyncio.run(scenario())
