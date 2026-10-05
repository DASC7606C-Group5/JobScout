"""Group 6 acceptance tests with fixed profiles and normalized jobs."""

from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction

import pytest

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.profile import ProfilePreferences, ProfileSource, UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.services.recommendation_service import (
    RecommendationError,
    _evaluate,
    _extract_skill_terms,
    _skill_in_texts,
    recommend_jobs,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def make_profile() -> UserProfile:
    return UserProfile(
        profile_id="profile-group6",
        source=ProfileSource(description=True),
        skills=["Python", "SQL"],
        education=["Bachelor in Computer Science"],
        target_directions=["Data Analyst", "Backend Developer"],
        preferences=ProfilePreferences(location="Hong Kong", employment_type="internship"),
        confirmed_fields=["preferences.location", "preferences.employment_type"],
    )


def make_job(
    job_id: str,
    *,
    skills: list[str] | None = None,
    direction: str = "Data Analyst",
    status: FreshnessStatus = FreshnessStatus.ACTIVE,
    location: str = "Hong Kong",
    title: str = "Data Analyst Intern",
    responsibilities: list[str] | None = None,
) -> JobPosting:
    return JobPosting(
        job_id=job_id,
        source="mock-group6",
        source_url=f"https://example.com/jobs/{job_id}",
        source_links=[f"https://example.com/jobs/{job_id}", f"https://example.org/jobs/{job_id}"],
        title=title,
        company=f"Example {job_id}",
        location=location,
        salary="HKD 10,000/month",
        target_direction=direction,
        required_skills=["Python", "SQL"] if skills is None else skills,
        responsibilities=["Analyse data"] if responsibilities is None else responsibilities,
        posted_at=NOW - timedelta(days=1),
        fetched_at=NOW,
        freshness_status=status,
    )


def run(profile: UserProfile, jobs: list[JobPosting]) -> RecommendationResult:
    return recommend_jobs(profile, jobs, session_id="session-group6", now=NOW)


def test_overall_top_five_and_complete_schema_fields() -> None:
    jobs = [
        make_job(f"job-{i}", direction="Backend Developer" if i % 2 else "Data Analyst")
        for i in range(8)
    ]
    result = run(make_profile(), list(reversed(jobs)))
    assert [item.job.job_id for item in result.jobs] == [f"job-{i}" for i in range(5)]
    assert {item.job.target_direction for item in result.jobs} == {
        "Data Analyst",
        "Backend Developer",
    }
    assert result.session_id == "session-group6"
    assert result.generated_at == NOW
    assert all(item.preparation_suggestions for item in result.jobs)
    assert [item.job for item in result.jobs] == jobs[:5]
    assert RecommendationResult.model_validate_json(result.model_dump_json()) == result


def test_skill_coverage_ranks_a_better_match_first() -> None:
    result = run(make_profile(), [make_job("a", skills=["Python", "SQL", "R"]), make_job("z")])
    assert [item.job.job_id for item in result.jobs] == ["z", "a"]


@pytest.mark.parametrize("field", ["internships", "projects"])
def test_background_affects_ranking_without_claiming_a_skill(field: str) -> None:
    profile = make_profile()
    profile.skills = []
    setattr(profile, field, ["Built a Python dashboard"])
    result = run(profile, [make_job("a", skills=["SQL"]), make_job("z", skills=["Python"])])
    assert [item.job.job_id for item in result.jobs] == ["z", "a"]


@pytest.mark.parametrize(
    "requirement", ["Bachelor's degree required", "Bachelor's or Master's degree required"]
)
def test_education_is_compared_to_explicit_job_requirements(requirement: str) -> None:
    result = run(
        make_profile(),
        [
            make_job("a", responsibilities=["Master's degree required"]),
            make_job("z", responsibilities=[requirement]),
        ],
    )
    assert [item.job.job_id for item in result.jobs] == ["z", "a"]


def test_expired_is_excluded_and_unknown_preserved_after_active() -> None:
    result = run(
        make_profile(),
        [
            make_job("expired", status=FreshnessStatus.EXPIRED),
            make_job("unknown", status=FreshnessStatus.UNKNOWN),
            make_job("active", skills=["Rust"]),
        ],
    )
    assert [item.job.job_id for item in result.jobs] == ["active", "unknown"]
    assert result.jobs[1].job.freshness_status == FreshnessStatus.UNKNOWN


def test_off_direction_jobs_are_excluded() -> None:
    result = run(make_profile(), [make_job("a", direction="Sales"), make_job("b")])
    assert [item.job.job_id for item in result.jobs] == ["b"]


def test_confirmed_location_filters_mismatches_but_keeps_unknown() -> None:
    result = run(
        make_profile(),
        [
            make_job("a", location="Shanghai"),
            make_job("b", location="Hong Kong SAR"),
            make_job("c", location="unknown"),
        ],
    )
    assert {item.job.job_id for item in result.jobs} == {"b", "c"}


@pytest.mark.parametrize("requested", ["香港", "Hong Kong", "HK", "ＨＫ", "Hong Kong SAR"])
@pytest.mark.parametrize("actual", ["Hong Kong", "香港", "HK", "Hong Kong SAR", "香港特別行政區"])
def test_confirmed_hong_kong_location_aliases_are_equivalent(requested: str, actual: str) -> None:
    profile = make_profile()
    profile.preferences.location = requested
    candidate = make_job("a", location=actual)
    result = run(profile, [candidate])
    assert [item.job for item in result.jobs] == [candidate]
    assert profile.preferences.location == requested
    assert result.jobs[0].job.location == actual


@pytest.mark.parametrize(
    ("requested", "actual"),
    [
        ("香港", "Shanghai"),
        ("HK", "HKUST Guangzhou"),
        ("Hong Kong Central", "Hong Kong"),
        ("香港中环", "香港"),
        ("Shanghai", "Hong Kong"),
    ],
)
def test_location_aliases_do_not_broaden_specific_constraints(requested: str, actual: str) -> None:
    profile = make_profile()
    profile.preferences.location = requested
    assert run(profile, [make_job("a", location=actual)]).jobs == []


@pytest.mark.parametrize(
    ("chinese", "english"),
    [
        ("北京", "Beijing"),
        ("上海", "Shanghai"),
        ("广州", "Guangzhou"),
        ("深圳", "Shenzhen"),
        ("杭州", "Hangzhou"),
        ("成都", "Chengdu"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_existing_source_city_aliases_match_without_changing_locations(
    chinese: str, english: str, reverse: bool
) -> None:
    profile = make_profile()
    profile.preferences.location = english if reverse else chinese + "市"
    candidate = make_job("a", location=chinese + "市" if reverse else english)
    assert [item.job for item in run(profile, [candidate]).jobs] == [candidate]


@pytest.mark.parametrize(
    ("requested", "actual"),
    [
        ("Shanghai", "Beijing"),
        ("深圳", "Guangzhou"),
        ("Shanghai Pudong", "Shanghai"),
        ("上海浦东", "上海市"),
        ("北京", "Beijingville"),
        ("上海/北京", "Shanghai"),
    ],
)
def test_city_aliases_do_not_equate_regions_or_erase_districts(requested: str, actual: str) -> None:
    profile = make_profile()
    profile.preferences.location = requested
    assert run(profile, [make_job("a", location=actual)]).jobs == []


def test_unconfirmed_preferences_are_not_used_as_filters() -> None:
    profile = make_profile()
    profile.confirmed_fields = []
    assert (
        len(run(profile, [make_job("a", location="Shanghai", title="Full-time Analyst")]).jobs) == 1
    )


def test_confirmed_unrestricted_location_does_not_filter() -> None:
    profile = make_profile()
    profile.preferences.location = None
    profile.preferences.location_unrestricted = True
    profile.confirmed_fields = ["preferences.location_unrestricted"]
    assert len(run(profile, [make_job("a", location="Shanghai")]).jobs) == 1


def test_confirmed_employment_filters_mismatch_and_warns_on_unknown() -> None:
    result = run(
        make_profile(),
        [
            make_job("a", title="Full-time Analyst"),
            make_job("b", title="Data Analyst"),
            make_job("c", title="Data Analyst Internship"),
        ],
    )
    assert {item.job.job_id for item in result.jobs} == {"b", "c"}


def test_employment_label_is_used_but_colleague_mentions_are_not() -> None:
    result = run(
        make_profile(),
        [
            make_job("a", title="Analyst", responsibilities=["Employment type: full-time"]),
            make_job("b", title="Analyst", responsibilities=["Work with full-time colleagues"]),
            make_job("c", title="Analyst", responsibilities=["工作类型：实习"]),
        ],
    )
    assert {item.job.job_id for item in result.jobs} == {"b", "c"}


def test_structured_employment_metadata_takes_precedence_over_title() -> None:
    mismatch = make_job("mismatch")
    mismatch.employment_type = "full-time"
    match = make_job("match", title="Full-time team analyst")
    match.employment_type = "internship"
    result = run(make_profile(), [mismatch, match])
    assert [item.job.job_id for item in result.jobs] == ["match"]


def test_explicit_unrestricted_employment_overrides_stale_type() -> None:
    profile = make_profile()
    profile.preferences.employment_type_unrestricted = True
    profile.confirmed_fields.append("preferences.employment_type_unrestricted")
    result = run(profile, [make_job("a", title="Full-time Analyst")])
    assert len(result.jobs) == 1


def test_merged_direction_tags_retain_an_eligible_vacancy() -> None:
    candidate = make_job("a", direction="Sales")
    candidate.target_directions = ["Data Analyst"]
    assert len(run(make_profile(), [candidate]).jobs) == 1


def test_unverifiable_optional_preferences_are_reported() -> None:
    profile = make_profile()
    profile.preferences.salary_range = "HKD 12,000/month or more"
    profile.preferences.work_mode = "remote"
    profile.preferences.industry = "finance"
    profile.confirmed_fields.extend(
        ["preferences.salary_range", "preferences.work_mode", "preferences.industry"]
    )
    result = run(profile, [make_job("a")])
    assert len(result.jobs) == 1
    assert {
        notice.preference for notice in result.notices if notice.code == "preference_unverified"
    } == {"salary_range", "work_mode", "industry"}


def test_skill_aliases_whitespace_and_case_preserve_coverage_score() -> None:
    profile = make_profile()
    profile.skills = [" javascript ", "K8S", "POSTGRES", "Ｃ＋＋"]
    candidate = _evaluate(
        profile, make_job("a", skills=["JS", "Kubernetes", "PostgreSQL", "C++", " R ", "r"])
    )
    assert candidate.score == 56


def test_skill_names_do_not_match_substrings_or_other_languages() -> None:
    profile = make_profile()
    profile.skills = ["JavaScript", "C++", "C#"]
    profile.projects = ["JavaScript and C++ project"]
    candidate = _evaluate(profile, make_job("a", skills=["Java", "C", "C#"]))
    assert candidate.score == Fraction(70, 3)


def test_chinese_experience_location_and_education() -> None:
    profile = make_profile()
    profile.preferences.location = "上海"
    profile.education = ["计算机科学本科"]
    profile.projects = ["使用Python构建数据分析项目"]
    result = run(
        profile, [make_job("a", location="上海市", responsibilities=["学历要求：本科及以上"])]
    )
    assert len(result.jobs) == 1


def test_missing_job_skills_do_not_claim_a_perfect_match() -> None:
    result = run(make_profile(), [make_job("a", skills=[]), make_job("z")])
    assert [item.job.job_id for item in result.jobs] == ["z", "a"]


@pytest.mark.parametrize("jobs", [[], [make_job("expired", status=FreshnessStatus.EXPIRED)]])
def test_empty_or_fully_filtered_input_returns_empty_result(jobs: list[JobPosting]) -> None:
    result = run(make_profile(), jobs)
    assert result.jobs == []


def test_fewer_than_five_jobs_are_not_padded() -> None:
    assert len(run(make_profile(), [make_job("a"), make_job("b")]).jobs) == 2


def test_duplicate_id_does_not_occupy_multiple_slots_or_merge_here() -> None:
    first = make_job("a")
    result = run(make_profile(), [first, make_job("a", skills=["Rust"])])
    assert len(result.jobs) == 1
    assert result.jobs[0].job == first


def test_stable_order_and_no_mutation_or_shared_result_objects() -> None:
    profile = make_profile()
    jobs = [make_job("c"), make_job("a"), make_job("b")]
    before = [job.model_dump_json() for job in jobs]
    before_profile = profile.model_dump_json()
    result = run(profile, jobs)
    assert result == run(profile, list(reversed(jobs)))
    assert [job.model_dump_json() for job in jobs] == before
    assert profile.model_dump_json() == before_profile
    result.jobs[0].job.required_skills.append("Rust")
    assert [job.model_dump_json() for job in jobs] == before


@pytest.mark.parametrize("field", ["missing_required_fields", "conflicts", "target_directions"])
def test_unready_profile_raises_a_shared_error(field: str) -> None:
    profile = make_profile()
    setattr(profile, field, [] if field == "target_directions" else ["needs confirmation"])
    with pytest.raises(RecommendationError) as exc:
        run(profile, [make_job("a")])
    assert exc.value.error.code == "recommendation_profile_not_ready"
    assert exc.value.error.stage == "recommend"
    assert WorkflowError.model_validate_json(exc.value.error.model_dump_json()) == exc.value.error


def test_invalid_session_and_naive_timestamp_raise_shared_errors() -> None:
    with pytest.raises(RecommendationError, match="session_id"):
        recommend_jobs(make_profile(), [], session_id=" ", now=NOW)
    with pytest.raises(RecommendationError) as exc:
        recommend_jobs(make_profile(), [], session_id="s", now=NOW.replace(tzinfo=None))
    assert exc.value.error.code == "recommendation_invalid_time"


def test_injected_time_is_converted_to_utc() -> None:
    result = recommend_jobs(
        make_profile(), [], session_id="s", now=NOW.astimezone(timezone(timedelta(hours=8)))
    )
    assert result.generated_at == NOW
    assert result.generated_at.tzinfo == UTC


@pytest.mark.parametrize(
    "text", ["React, TypeScript", "React / TypeScript", "Experience using React and TypeScript"]
)
def test_compound_skill_fields_do_not_require_a_verbatim_resume_phrase(text: str) -> None:
    assert set(_extract_skill_terms(text, ["React", "TypeScript"])) == {"React", "TypeScript"}


def test_skill_aliases_work_in_both_language_directions_and_keep_open_ended_names() -> None:
    assert _skill_in_texts("API 对接", ["API integration"])
    assert _skill_in_texts("API integration", ["API 对接"])
    assert _extract_skill_terms("User Experience Design") == ["User Experience Design"]
