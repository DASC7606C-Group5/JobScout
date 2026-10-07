"""Deterministic arithmetic, source isolation and score input contracts."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from jobscout.graph.checkpoints import checkpoint_serializer
from jobscout.schemas.matching import (
    DIMENSION_WEIGHTS,
    DimensionAssessment,
    MatchDimension,
    MatchScore,
)
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.services.job_assessment_service import (
    JobAnalysis,
    JobAssessmentService,
    Requirement,
    SourceQuote,
)
from jobscout.services.matching_score import aggregate, build_match_score
from jobscout.services.ranking import recommendation_key
from tests.test_job_assessment_service import PROFILE_DOCUMENTS, ReplayProvider, job, profile


def dimensions(
    scores: dict[str, int | None], excluded: set[str] | None = None
) -> list[MatchDimension]:
    return [
        MatchDimension(
            id=identity,
            weight=weight,
            score=scores.get(identity),
            status="not_applicable"
            if identity in (excluded or set())
            else "assessed"
            if scores.get(identity) is not None
            else "unknown",
            input_hash=identity,
        )
        for identity, weight in DIMENSION_WEIGHTS.items()
    ]


def test_exact_weights_half_up_and_partial_denominator() -> None:
    result = aggregate(
        dimensions(
            {
                "skills": 80,
                "responsibilities": 60,
                "experience": 40,
                "seniority": 20,
                "education": 100,
                "preferences": 90,
            }
        )
    )
    assert result.total == 63
    assert result.assessed_percentage == 100 and not result.provisional
    partial = aggregate(dimensions({"skills": 80, "preferences": 50}, {"education"}))
    assert partial.total is None
    assert (partial.assessed_weight, partial.applicable_weight, partial.assessed_percentage) == (
        40,
        95,
        42,
    )
    assert partial.provisional and partial.completeness == "partial"
    assert partial.dimensions[0].score == 80
    enough = aggregate(
        dimensions({"skills": 72, "responsibilities": 74, "experience": 72, "education": 70})
    )
    assert enough.total == 73  # 5800 / 80 = 72.5
    unknown = aggregate(dimensions({}))
    assert unknown.total is None and unknown.assessed_percentage == 0
    assert unknown.completeness == "unknown"


def test_low_assessed_percentage_does_not_outrank_supported_fit_and_ties_use_job_id() -> None:
    sparse = RecommendationItem(
        job=job("a"),
        recommendation_fit="recommended",
        match_score=aggregate(dimensions({"education": 100})),
    )
    supported = RecommendationItem(
        job=job("b"),
        recommendation_fit="recommended",
        match_score=aggregate(dimensions({"skills": 60, "responsibilities": 60, "experience": 60})),
    )
    tied = supported.model_copy(update={"job": job("c")})
    assert [i.job.job_id for i in sorted([tied, sparse, supported], key=recommendation_key)] == [
        "b",
        "c",
        "a",
    ]
    excluded = supported.model_copy(update={"recommendation_fit": "unlikely"})
    assert recommendation_key(sparse) < recommendation_key(excluded)
    incomplete = supported.model_copy(update={"analysis_status": "partial"})
    assert recommendation_key(incomplete) == recommendation_key(supported)


def judgment(identity: str, requirement: str, fact: str, excerpt: str) -> DimensionAssessment:
    return DimensionAssessment.model_validate(
        {
            "id": identity,
            "status": "assessed",
            "score": 80,
            "explanation": "Directly meets the requirement",
            "requirement_ids": [requirement],
            "profile_fact_ids": [fact],
            "job_source_quotes": [{"document_id": "jd", "excerpt": requirement}],
            "profile_source_quotes": [{"document_id": "resume", "excerpt": excerpt}],
        }
    )


def test_bad_reference_isolated_and_input_changes_invalidate() -> None:
    analysis = JobAnalysis(
        job_id="j",
        requirements=[
            Requirement(
                requirement_id="Python",
                text="Python",
                category="skill",
                source_quotes=[SourceQuote(document_id="jd", excerpt="Python")],
            ),
            Requirement(
                requirement_id="degree",
                text="degree",
                category="education",
                source_quotes=[SourceQuote(document_id="jd", excerpt="degree")],
            ),
        ],
    )
    rows = [
        judgment("skills", "Python", "skills:0", "Python"),
        judgment("education", "degree", "education:0", "invented"),
    ]
    applicant = profile()

    def score() -> MatchScore:
        return build_match_score(
            rows,
            analysis,
            applicant,
            {"jd": "Python degree"},
            {"resume": "Python Bachelor of Computer Science"},
        )

    first = score()
    assert first.dimensions[0].score == 80
    assert first.dimensions[4].status == "unknown"
    assert first.total is None and first.assessed_percentage == 30 and first.provisional
    applicant.preferences.location = "Shanghai"
    preference_change = score()
    assert first.dimensions[0].input_hash == preference_change.dimensions[0].input_hash
    assert first.dimensions[5].input_hash != preference_change.dimensions[5].input_hash
    applicant.skills = ["SQL"]
    assert preference_change.dimensions[0].input_hash != score().dimensions[0].input_hash
    assert "interest" not in DimensionAssessment.model_fields
    rows[0].profile_source_quotes[0].excerpt = "absent"
    assert score().total is None


def test_dimension_contract_rejects_numeric_unknown() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Only assessed"):
        DimensionAssessment(id="skills", score=0, status="unknown")


def test_cached_dimension_survives_checkpoint_preferences_and_unrelated_background() -> None:
    def supply_dimension(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            for row in response["jobs"]:
                row["dimensions"] = [
                    {
                        "id": "skills",
                        "score": 85,
                        "status": "assessed",
                        "explanation": "Python is documented",
                        "requirement_ids": ["python"],
                        "profile_fact_ids": ["skills:0"],
                        "job_source_quotes": [
                            {"document_id": f"doc-{row['job_id']}", "excerpt": "Python required."}
                        ],
                        "profile_source_quotes": [{"document_id": "resume", "excerpt": "Python"}],
                    }
                ]

    async def scenario() -> None:
        provider = ReplayProvider(supply_dimension)
        service = JobAssessmentService(provider)
        await service.begin_search("search")
        applicant = profile()
        result = await service.assess(applicant, [job("j")], PROFILE_DOCUMENTS, "s")
        initial = result.jobs[0].match_score
        assert initial is not None and initial.dimensions[0].score == 85
        snapshot = json.loads(json.dumps(service.export_cache()))
        restarted = JobAssessmentService(provider)
        restarted.import_cache(snapshot, "s")
        await restarted.begin_search("next-search")
        applicant.preferences.work_mode = "hybrid"
        applicant.education.append("New certificate")

        def alternate(task: str, response: dict[str, Any]) -> None:
            supply_dimension(task, response)
            if task == "matching":
                for row in response["jobs"]:
                    row["dimensions"][0]["score"] = 30

        provider.mutate = alternate
        next_result = await restarted.assess(applicant, [job("j")], PROFILE_DOCUMENTS, "s")
        continued = next_result.jobs[0].match_score
        assert continued is not None and continued.dimensions[0] == initial.dimensions[0]
        assert continued.dimensions[4].input_hash != initial.dimensions[4].input_hash
        assert continued.dimensions[5].input_hash != initial.dimensions[5].input_hash
        applicant.skills.append("SQL")
        changed = await restarted.assess(applicant, [job("j")], PROFILE_DOCUMENTS, "s")
        assert changed.jobs[0].match_score is not None
        assert changed.jobs[0].match_score.dimensions[0].score == 30
        changed_background = await restarted.assess(
            applicant, [job("j")], {"resume": "Bachelor of Computer Science"}, "s"
        )
        assert changed_background.jobs[0].match_score is not None
        assert changed_background.jobs[0].match_score.total is None

    asyncio.run(scenario())


def test_score_survives_durable_workflow_serializer() -> None:
    score = aggregate(dimensions({"skills": 80, "responsibilities": 70}))
    result = RecommendationResult(
        session_id="s",
        generated_at=datetime.now(UTC),
        jobs=[RecommendationItem(job=job("j"), match_score=score)],
    )
    serializer = checkpoint_serializer()
    restored = serializer.loads_typed(serializer.dumps_typed({"recommendation": result}))
    assert restored["recommendation"].jobs[0].match_score == score


def test_holistic_dimensions_accept_normalized_facts_and_cross_category_requirements() -> None:
    applicant = profile()
    applicant.skills = ["Python", "SQL"]
    applicant.projects = ["Sales dashboard using Python and PostgreSQL"]
    listing = "Use Python and SQL. Present weekly dashboards. Full-time experience is not required."
    raw_resume = (
        "Skills: Python and SQL. Completed a project presenting a weekly reporting dashboard."
    )
    analysis = JobAnalysis(
        job_id="j",
        requirements=[
            Requirement(
                requirement_id="tools",
                text="Use Python and SQL",
                category="skill",
                source_quotes=[SourceQuote(document_id="jd", excerpt="Use Python and SQL")],
            ),
            Requirement(
                requirement_id="duties",
                text="Present weekly dashboards",
                category="responsibility",
                source_quotes=[SourceQuote(document_id="jd", excerpt="Present weekly dashboards")],
            ),
            Requirement(
                requirement_id="experience",
                text="Full-time experience is not required",
                category="experience",
                source_quotes=[
                    SourceQuote(document_id="jd", excerpt="Full-time experience is not required")
                ],
            ),
        ],
    )
    skill = judgment("skills", "tools", "skills:0", "Python and SQL")
    skill.job_source_quotes[0].excerpt = "Use Python and SQL"
    skill.profile_fact_ids = ["skills:0", "skills:1"]
    duties = judgment(
        "responsibilities", "duties", "projects:0", "presenting a weekly reporting dashboard"
    )
    duties.job_source_quotes[0].excerpt = "Present weekly dashboards"
    waived = DimensionAssessment.model_validate(
        {
            "id": "seniority",
            "status": "not_applicable",
            "explanation": "Full-time work is waived",
            "requirement_ids": ["experience"],
            "job_source_quotes": [
                {"document_id": "jd", "excerpt": "Full-time experience is not required"}
            ],
        }
    )
    score = build_match_score(
        [skill, duties, waived], analysis, applicant, {"jd": listing}, {"resume": raw_resume}
    )
    assert score.dimensions[0].score == 80
    assert score.dimensions[1].score == 80
    assert score.dimensions[3].status == "not_applicable"
    assert score.applicable_weight == 90 and score.assessed_percentage == 61
    assert (
        score.dimensions[1].profile_source_quotes[0].excerpt
        == "presenting a weekly reporting dashboard"
    )
