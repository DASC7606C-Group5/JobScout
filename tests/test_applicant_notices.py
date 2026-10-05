"""Applicant projections preserve source data while excluding operational diagnostics."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jobscout.main import create_app
from jobscout.schemas.conversation import MatchingReason, SourceQuoteReference
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.session import SessionResumeRequest
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.job_retrieval.models import SourceOutcome
from jobscout.services.notice_service import (
    finalize_recommendation,
    make_notice,
    source_notices,
)
from jobscout.services.session_service import SessionOperationError, SessionService, _Session

NOW = datetime(2026, 10, 6, tzinfo=UTC)
PRIVATE = "PRIVATE_DIAGNOSTIC_7db9"


def posting(**changes: Any) -> JobPosting:
    values: dict[str, Any] = {
        "job_id": "selected",
        "source": "jobsdb",
        "source_url": "https://example.org/selected",
        "title": "Application Engineer",
        "company": "Example",
        "location": "Hong Kong",
        "target_direction": "Engineering",
        "description": "Develop applications with Python.",
        "freshness_status": FreshnessStatus.ACTIVE,
        "fetched_at": NOW,
    }
    return JobPosting.model_validate(values | changes)


def test_notices_follow_final_merged_listing_instead_of_raw_record_gaps() -> None:
    first = posting(description="Python summary", description_is_excerpt=True).model_dump()
    second = first | {
        "source": "liepin",
        "source_url": "https://example.org/mirror",
        "description": "Python development and integration responsibilities.",
        "description_is_excerpt": False,
    }
    processed = process_jobs([first, second, {"title": PRIVATE}])
    assert processed.warnings  # Missing optional fields and the discarded record remain diagnostic.
    assert [job.job_id for job in processed.jobs] == ["selected"]
    raw_result = RecommendationResult(
        session_id="s",
        generated_at=NOW,
        jobs=[RecommendationItem(job=processed.jobs[0])],
        notices=[make_notice("analysis_unavailable", job_id="discarded")],
    )
    result = finalize_recommendation(raw_result)
    assert result.jobs[0].job == processed.jobs[0]
    assert result.jobs[0].notices == []
    assert result.notices == []
    assert "warnings" not in result.model_dump()
    assert not {"missing_skills", "uncertainty_notices"} & result.jobs[0].model_dump().keys()
    assert PRIVATE not in result.model_dump_json()


def test_job_notices_are_deduplicated_and_do_not_become_search_notices() -> None:
    job = posting(description="", freshness_status=FreshnessStatus.UNKNOWN)
    notice = make_notice("listing_incomplete", job_id=job.job_id)
    result = finalize_recommendation(
        RecommendationResult(
            session_id="s",
            generated_at=NOW,
            jobs=[RecommendationItem(job=job, notices=[notice], analysis_status="partial")],
            notices=[notice, notice, make_notice("analysis_unavailable", job_id="not-selected")],
        )
    )
    assert [(item.code, item.job_id) for item in result.jobs[0].notices] == [
        ("listing_incomplete", "selected"),
        ("listing_status_unverified", "selected"),
        ("analysis_partial", "selected"),
    ]
    assert all(item.action == "open_listing" for item in result.jobs[0].notices)
    assert result.notices == []
    assert finalize_recommendation(result) == result


def test_diagnostic_shaped_original_content_and_exact_quotes_are_preserved() -> None:
    original = "Group 6 builds Python applications; None is a Python value."
    reason = MatchingReason(
        requirement="Python",
        level="partial",
        explanation="A supplied project involves Python.",
        job_source_quotes=[SourceQuoteReference(document_id="job-source", excerpt=original)],
        profile_source_quotes=[SourceQuoteReference(document_id="resume", excerpt=original)],
    )
    item = RecommendationItem(
        job=posting(description=original),
        matching_reasons=[reason],
    )
    result = finalize_recommendation(
        RecommendationResult(session_id="s", generated_at=NOW, jobs=[item])
    )
    assert result.jobs[0].job.description == original
    assert result.jobs[0].matching_reasons == [reason]
    assert PRIVATE not in result.model_dump_json()


def test_notice_contract_rejects_unknown_operator_codes() -> None:
    notice = make_notice("coverage_limited", source="jobsdb").model_dump()
    with pytest.raises(ValidationError) as rejected:
        ApplicantNotice.model_validate(notice | {"code": "operator_configuration"})
    assert [(error["loc"], error["type"]) for error in rejected.value.errors()] == [
        (("code",), "literal_error")
    ]


def test_source_failures_aggregate_across_rounds_and_preserve_source_identity() -> None:
    outcomes = [
        SourceOutcome(source="jobsdb", target_direction="Engineering", status="unavailable"),
        SourceOutcome(source="jobsdb", target_direction="Engineering", status="ok"),
        SourceOutcome(source="liepin", target_direction="Engineering", status="blocked"),
        SourceOutcome(source="liepin", target_direction="Engineering", status="blocked"),
    ]
    assert [(notice.code, notice.source) for notice in source_notices(outcomes)] == [
        ("source_partial", "jobsdb"),
        ("source_unavailable", "liepin"),
    ]


def test_only_confirmed_unverified_preferences_produce_notices() -> None:
    profile = UserProfile(
        profile_id="p",
        preferences=ProfilePreferences(salary_range="30000", work_mode="remote", location="HK"),
        confirmed_fields=["preferences.salary_range", "preferences.location"],
    )
    result = finalize_recommendation(
        RecommendationResult(
            session_id="s", generated_at=NOW, jobs=[RecommendationItem(job=posting(location=""))]
        ),
        profile=profile,
    )
    assert [(notice.code, notice.preference) for notice in result.notices] == [
        ("preference_unverified", "salary_range")
    ]
    assert [
        (notice.code, notice.preference, notice.job_id) for notice in result.jobs[0].notices
    ] == [("preference_unverified", "location", "selected")]


def test_session_projection_keeps_diagnostics_private_and_honors_retryability() -> None:
    async def check() -> None:
        manager = SessionService(object(), object())
        error = WorkflowError(
            code="model_auth", message=PRIVATE, stage="private-stage", details={"secret": PRIVATE}
        )
        record = _Session(
            "s",
            {
                "errors": [error],
                "source_errors": [error],
                "warnings": [PRIVATE],
                "retryable": False,
            },
            outcome="failed",
        )
        manager.sessions["s"] = record
        response = await manager.get("s")
        assert [(item.code, item.action) for item in response.errors] == [
            ("service_unavailable", "edit_conditions")
        ]
        assert response.retryable is False
        assert "warnings" not in response.model_dump()
        assert PRIVATE not in response.model_dump_json()
        assert record.state["errors"] == [error]
        with pytest.raises(SessionOperationError) as rejected:
            await manager.resume(
                "s", SessionResumeRequest(request_id="retry", expected_revision=1, action="retry")
            )
        assert rejected.value.code == "search_not_retryable"
        assert record.revision == 1

    asyncio.run(check())


def test_http_missing_search_and_validation_failures_return_public_codes() -> None:
    with TestClient(create_app(graph=object())) as client:
        missing = client.get("/api/v1/sessions/missing")
        malformed = client.post("/api/v1/sessions", json={"request_id": {PRIVATE: PRIVATE}})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "search_not_found"
    assert missing.json()["detail"]["action"] == "start_new_search"
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_input"
    assert PRIVATE not in malformed.text


def test_unexpected_http_failure_retains_status_and_hides_exception_details() -> None:
    application = create_app(graph=object())

    @application.get("/test-unexpected-failure")
    def unexpected_failure() -> None:
        raise RuntimeError(PRIVATE)

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/test-unexpected-failure")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "service_unavailable"
    assert response.json()["detail"]["action"] == "retry"
    assert PRIVATE not in response.text
