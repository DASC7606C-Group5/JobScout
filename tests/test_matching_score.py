"""Deterministic arithmetic, evidence isolation and score input contracts."""

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
            input_fingerprint=identity,
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
    assert result.coverage == 100 and not result.provisional
    partial = aggregate(dimensions({"skills": 80, "preferences": 50}, {"education"}))
    assert partial.total == 73  # 2900 / 40 = 72.5
    assert (partial.assessed_weight, partial.applicable_weight, partial.coverage) == (40, 95, 42)
    assert partial.provisional and partial.completeness == "partial"
    unknown = aggregate(dimensions({}))
    assert unknown.total is None and unknown.coverage == 0
    assert unknown.completeness == "unknown"


def test_low_coverage_does_not_outrank_supported_fit_and_ties_use_job_id() -> None:
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
    assert recommendation_key(tied) < recommendation_key(incomplete)


def judgment(identity: str, requirement: str, fact: str, excerpt: str) -> DimensionAssessment:
    return DimensionAssessment.model_validate(
        {
            "id": identity,
            "status": "assessed",
            "score": 80,
            "explanation": "Direct evidence",
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
    assert first.total == 80 and first.coverage == 30 and first.provisional
    applicant.preferences.location = "Shanghai"
    preference_change = score()
    assert (
        first.dimensions[0].input_fingerprint == preference_change.dimensions[0].input_fingerprint
    )
    assert (
        first.dimensions[5].input_fingerprint != preference_change.dimensions[5].input_fingerprint
    )
    applicant.skills = ["SQL"]
    assert (
        preference_change.dimensions[0].input_fingerprint != score().dimensions[0].input_fingerprint
    )
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
        assert continued.dimensions[4].input_fingerprint != initial.dimensions[4].input_fingerprint
        assert continued.dimensions[5].input_fingerprint != initial.dimensions[5].input_fingerprint
        applicant.skills.append("SQL")
        changed = await restarted.assess(applicant, [job("j")], PROFILE_DOCUMENTS, "s")
        assert changed.jobs[0].match_score is not None
        assert changed.jobs[0].match_score.dimensions[0].score == 30
        changed_evidence = await restarted.assess(
            applicant, [job("j")], {"resume": "Bachelor of Computer Science"}, "s"
        )
        assert changed_evidence.jobs[0].match_score is not None
        assert changed_evidence.jobs[0].match_score.total is None

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
