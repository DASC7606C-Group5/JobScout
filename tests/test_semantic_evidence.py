"""Evidence contracts use model-normalized meanings, never local language vocabularies."""

from typing import Any

import pytest

from jobscout.schemas.profile import UserProfile
from jobscout.services.job_assessment_service import _profile_facts
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.job_retrieval.local_sources import observed_employment_type
from jobscout.services.job_retrieval.models import RawJob
from jobscout.services.recommendation_service import eligible_jobs
from tests.test_job_assessment_service import ReplayProvider, assess, job, profile
from tests.test_job_processing_service import make_raw


def evaluate(
    requirement: dict[str, Any],
    match: dict[str, Any],
    applicant: UserProfile,
    excerpt: str,
    *,
    advice: str = "",
) -> Any:
    candidate = job("semantic")
    candidate.description = requirement["text"]
    candidate.source_documents[0].text = requirement["text"]

    def respond(task: str, response: dict[str, Any]) -> None:
        row = response["jobs"][0]
        if task == "jd_analysis":
            row["requirements"] = [
                {
                    "requirement_id": "r1",
                    "source_quotes": [
                        {"document_id": "doc-semantic", "excerpt": requirement["text"]}
                    ],
                    **requirement,
                }
            ]
        elif task == "matching":
            row["matches"] = [
                {
                    "requirement_id": "r1",
                    "level": "strong",
                    "profile_source_quotes": [{"document_id": "original", "excerpt": excerpt}],
                    **match,
                }
            ]
            row["preparation_suggestions"] = (
                [{"requirement_id": "r1", "suggestion": advice}] if advice else []
            )

    return assess(ReplayProvider(respond), [candidate], applicant, {"original": excerpt})


@pytest.mark.parametrize("wording", ["BSc required", "須具學士學位", "理学士以上"])
def test_education_normalization_accepts_abbreviations_and_traditional_chinese(
    wording: str,
) -> None:
    applicant = profile()
    applicant.education = ["Bachelor of Science, Computer Science"]
    result = evaluate(
        {
            "text": wording,
            "category": "education",
            "qualification_options": ["Bachelor of Science"],
        },
        {
            "profile_fact_ids": ["education:0"],
            "qualifications": ["Bachelor of Science"],
            "qualification_relation": "meets",
        },
        applicant,
        "獲頒理學士（榮譽）",
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert (
        result.jobs[0].matching_reasons[0].profile_source_quotes[0].excerpt == "獲頒理學士（榮譽）"
    )


@pytest.mark.parametrize("actual", ["partial", "does_not_meet", "unknown", None])
def test_strong_education_match_requires_sufficient_normalized_qualification(
    actual: str | None,
) -> None:
    result = evaluate(
        {"text": "MSc required", "category": "education", "qualification_options": ["MSc"]},
        {
            "profile_fact_ids": ["education:0"],
            "qualifications": ["BSc"],
            "qualification_relation": actual,
        },
        profile(),
        "BSc in Computer Science",
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert result.jobs[0].matching_reasons == []
    assert result.jobs[0].analysis_status == "unavailable"


@pytest.mark.parametrize(
    ("wording", "minimum", "actual", "accepted"),
    [
        ("三年工作经验", 36, 36, True),
        ("半年经验", 6, 6, True),
        ("three years of experience", 36, 6, False),
        ("至少半年", 6, None, False),
    ],
)
def test_work_duration_compares_normalized_months_with_employment_evidence(
    wording: str,
    minimum: int,
    actual: int | None,
    accepted: bool,
) -> None:
    applicant = profile()
    applicant.internships = ["Worked as a data analyst"]
    excerpt = "Employment: January 2023 to January 2026, Data Analyst."
    result = evaluate(
        {"text": wording, "category": "experience", "minimum_experience_months": minimum},
        {
            "profile_fact_ids": ["internships:0"],
            "experience_fact_ids": ["internships:0"],
            "experience_source_quotes": [{"document_id": "original", "excerpt": excerpt}],
            "experience_months": actual,
        },
        applicant,
        excerpt,
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert bool(result.jobs[0].matching_reasons) is accepted
    assert result.jobs[0].analysis_status == ("complete" if accepted else "unavailable")


def test_project_duration_cannot_be_counted_as_employment() -> None:
    excerpt = "Spent three years building a personal dashboard."
    applicant = profile()
    applicant.projects = [excerpt]
    result = evaluate(
        {"text": "三年工作经验", "category": "experience", "minimum_experience_months": 36},
        {
            "profile_fact_ids": ["projects:0"],
            "experience_fact_ids": ["projects:0"],
            "experience_source_quotes": [{"document_id": "original", "excerpt": excerpt}],
            "experience_months": 36,
        },
        applicant,
        excerpt,
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert result.jobs[0].matching_reasons == []
    assert result.jobs[0].analysis_status == "unavailable"


def test_semantically_linked_short_evidence_and_unlisted_skill_advice_are_preserved() -> None:
    applicant = profile()
    applicant.skills = ["OpenTelemetry"]
    advice = "Instrument a small service with OpenTelemetry and explain the resulting traces."
    result = evaluate(
        {"text": "OpenTelemetry", "category": "skill"},
        {"profile_fact_ids": ["skills:0"]},
        applicant,
        "OTel",
        advice=advice,
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert result.jobs[0].preparation_suggestions == [advice]
    assert result.jobs[0].matching_reasons[0].profile_source_quotes[0].excerpt == "OTel"


@pytest.mark.parametrize("fact_ids", [[], ["skills:100"], ["education:0"], ["skills:0"]])
def test_invalid_or_wrong_category_fact_ids_cannot_prove_education(fact_ids: list[str]) -> None:
    applicant = profile()
    applicant.education = []
    result = evaluate(
        {"text": "BSc required", "category": "education", "qualification_options": ["BSc"]},
        {
            "profile_fact_ids": fact_ids,
            "qualifications": ["BSc"],
            "qualification_relation": "meets",
        },
        applicant,
        "BSc",
    )
    assert [row.job.job_id for row in result.jobs] == ["semantic"]
    assert result.jobs[0].matching_reasons == []
    assert result.jobs[0].analysis_status == "unavailable"


def test_current_fact_catalog_preserves_full_text_and_field_identity() -> None:
    applicant = profile()
    applicant.skills = ["CI/CD", "UI/UX"]
    facts = _profile_facts(applicant)
    assert facts["skills:0"] == {"field": "skills", "text": "CI/CD"}
    assert facts["skills:1"] == {"field": "skills", "text": "UI/UX"}
    assert facts["education:0"]["text"] == applicant.education[0]


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["FULL_TIME", "全職"], "full-time"),
        (["Full-time", "Internship"], "Full-time; Internship"),
        (["Graduate traineeship"], "Graduate traineeship"),
    ],
)
def test_native_employment_mapping_preserves_unknown_or_multiple_types(
    labels: list[str],
    expected: str,
) -> None:
    raw = make_raw(raw_payload={"job_types": labels})
    normalized = process_jobs([raw]).jobs[0]
    assert normalized.employment_type == expected
    assert raw["raw_payload"] == {"job_types": labels}
    if expected != "full-time":
        applicant = profile()
        applicant.target_directions = [normalized.target_direction]
        assert [row.job_id for row in eligible_jobs(applicant, [normalized])] == [normalized.job_id]


def test_local_source_keeps_listing_and_detail_employment_evidence_together() -> None:
    raw = RawJob(
        source="jobsdb",
        source_url="https://example.org/job",
        fetched_at=job("x").fetched_at,
        target_direction="Data",
        raw_payload={
            "workTypes": ["Full-time"],
            "detail_structured": {"employmentType": "Internship"},
        },
    )
    assert observed_employment_type(raw) == "Full-time; Internship"
    assert raw.raw_payload["workTypes"] == ["Full-time"]
