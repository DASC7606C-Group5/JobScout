"""Shared recommendation guards and pre-analysis candidate eligibility."""

from datetime import UTC, datetime

import pytest

from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.profile import (
    EmploymentCondition,
    LocationCondition,
    ProfilePreferences,
    UserProfile,
)
from jobscout.services.recommendation_service import (
    RecommendationError,
    _preference_check,
    eligible_jobs,
    validate_recommendation_profile,
)
from tests.location_fixtures import catalog_snapshot


@pytest.fixture(autouse=True)
def offline_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jobscout.services.location_service._catalog", catalog_snapshot())


def profile() -> UserProfile:
    return UserProfile(
        profile_id="applicant",
        target_directions=["Data Analyst", "Backend Developer"],
        preferences=ProfilePreferences(
            location="Hong Kong",
            employment_type="internship",
            locations=LocationCondition(included=catalog_snapshot().find("Hong Kong")),
            employment=EmploymentCondition(included=["internship"]),
        ),
    )


def job(identity: str, **updates: object) -> JobPosting:
    return JobPosting.model_validate(
        {
            "job_id": identity,
            "source": "synthetic",
            "source_url": f"https://snapshot.example/jobs/{identity}",
            "title": "Data Analyst Intern",
            "company": f"Company {identity}",
            "location": "Hong Kong",
            "employment_type": "internship",
            "target_direction": "Data Analyst",
            "freshness_status": "active",
            "fetched_at": datetime(2026, 10, 6, tzinfo=UTC),
            **updates,
        }
    )


@pytest.mark.parametrize("field", ["missing_required_fields", "conflicts", "target_directions"])
def test_unready_profile_is_rejected_before_analysis(field: str) -> None:
    applicant = profile()
    setattr(applicant, field, [] if field == "target_directions" else ["preferences.location"])
    before = applicant.model_dump()
    with pytest.raises(RecommendationError) as rejected:
        validate_recommendation_profile(applicant, "session")
    assert rejected.value.error.code == "recommendation_profile_not_ready"
    assert rejected.value.error.stage == "recommend"
    assert applicant.model_dump() == before


def test_blank_session_is_rejected_with_shared_error_code() -> None:
    with pytest.raises(RecommendationError) as rejected:
        validate_recommendation_profile(profile(), "   ")
    assert rejected.value.error.code == "recommendation_invalid_session"


def test_known_mismatches_are_excluded_and_unknown_facts_remain_candidates() -> None:
    candidates = [
        job("expired", freshness_status="expired"),
        job("off-direction", target_direction="Sales"),
        job("wrong-city", location="Beijing"),
        job("wrong-type", employment_type="full-time"),
        job(
            "unknown",
            location="Unresolved district",
            employment_type=None,
            freshness_status="unknown",
        ),
        job("allowed"),
    ]
    selected = eligible_jobs(profile(), candidates)
    assert [item.job_id for item in selected] == ["allowed", "unknown"]
    assert selected[1].freshness_status == FreshnessStatus.UNKNOWN
    assert _preference_check(profile(), selected[1]) == ([], ["location", "employment_type"])


def test_merged_direction_tags_keep_a_selected_direction_candidate() -> None:
    candidate = job("merged", target_direction="Sales", target_directions=["Data Analyst"])
    assert [item.job_id for item in eligible_jobs(profile(), [candidate])] == ["merged"]


def test_combinations_use_or_and_exclusions_preserve_district_uncertainty() -> None:
    applicant = profile()
    catalog = catalog_snapshot()
    applicant.preferences.locations = LocationCondition(
        included=[*catalog.find("Shanghai"), *catalog.find("Hong Kong")],
        excluded=catalog.find("Pudong"),
    )
    applicant.preferences.employment = EmploymentCondition(
        included=["internship", "part-time"], excluded=["contract"]
    )
    candidates = [
        job("district-excluded", location="Pudong"),
        job("hong-kong", employment_type="part-time"),
        job("city-needs-district", location="Shanghai"),
        job("city-excluded", location="Beijing"),
        job("type-excluded", employment_type="contract"),
    ]
    selected = eligible_jobs(applicant, candidates)
    assert [item.job_id for item in selected] == ["city-needs-district", "hong-kong"]
    assert _preference_check(applicant, selected[0]) == ([], ["location"])
    assert _preference_check(applicant, selected[1]) == ([], [])


def test_duplicate_identity_urls_and_vacancy_facts_do_not_inflate_candidates() -> None:
    original = job("a")
    candidates = [
        original,
        job("a", source_url="https://snapshot.example/jobs/z"),
        job("b", company=original.company),
        job("c", source_links=[original.source_url]),
        job("different"),
    ]
    applicant = profile()
    before = [item.model_dump() for item in candidates]
    original_profile = applicant.model_dump()
    selected = eligible_jobs(applicant, list(reversed(candidates)))
    assert [item.job_id for item in selected] == ["a", "different"]
    assert selected[0].source_url == original.source_url
    assert [item.model_dump() for item in candidates] == before
    assert applicant.model_dump() == original_profile
