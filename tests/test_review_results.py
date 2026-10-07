"""Regressions from full listings and summary-only reviews."""

import asyncio
from typing import Any

from jobscout.schemas.job import SourceDocument
from jobscout.schemas.job_status import ReviewIssue
from tests.test_job_assessment_service import NOW, ReplayProvider, assess, job, profile


def test_one_bad_job_does_not_discard_reviews_of_other_jobs() -> None:
    def damage(task: str, response: dict[str, Any]) -> None:
        if task == "matching" and response["jobs"][0]["job_id"] == "broken":
            response["jobs"][0]["recommendation_fit"] = "invalid"

    provider = ReplayProvider(damage)
    result = assess(provider, [job("first"), job("broken"), job("last")])
    rows = {row.job.job_id: row for row in result.jobs}
    assert rows["broken"].review_issue == ReviewIssue(code="invalid_output", stage="matching")
    assert rows["broken"].analysis_status == "unavailable"
    for identity in ("first", "last"):
        assert rows[identity].analysis_status == "complete"
        assert rows[identity].matching_reasons[0].level == "strong"
        assert rows[identity].recommendation_fit == "possible"
    requests = [call["jobs"] for call in provider.calls if call["task"] == "matching"]
    assert sorted([row["job_id"] for row in request] for request in requests) == [
        ["broken"],
        ["first"],
        ["last"],
    ]


def test_malformed_dimension_preserves_the_decision_and_valid_comparisons() -> None:
    reason = "Your Python dashboard work is relevant to the data tasks."

    def damage(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            row = response["jobs"][0]
            row["recommendation_reason"] = reason
            row["dimensions"] = [{"id": "skills", "status": "assessed", "score": 999}]

    item = assess(ReplayProvider(damage), [job("partial")]).jobs[0]
    assert item.analysis_status == "partial"
    assert item.recommendation_reason == reason
    assert item.matching_reasons[0].level == "strong"
    assert item.match_score is not None
    assert item.match_score.dimensions[0].status == "unknown"


def test_not_documented_keeps_explanation_despite_unused_support_fields() -> None:
    explanation = "Your profile does not mention Python; confirm whether you have used it."

    def change(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            row = response["jobs"][0]["matches"][0]
            row.update(
                level="not_documented",
                explanation=explanation,
                experience_months=0,
                qualification_relation="unknown",
            )

    item = assess(ReplayProvider(change), [job("missing-skill")]).jobs[0]
    assert item.analysis_status == "complete"
    assert item.matching_reasons[0].level == "not_documented"
    assert item.matching_reasons[0].explanation == explanation
    assert item.matching_reasons[0].profile_source_quotes == []
    assert item.review_issue is None


def test_unknown_quote_id_does_not_erase_valid_quoted_experience() -> None:
    def damage(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            response["jobs"][0]["matches"][0]["profile_quote_ids"] = ["missing", "p0"]

    item = assess(ReplayProvider(damage), [job("quoted")]).jobs[0]
    assert item.analysis_status == "partial"
    assert item.review_issue == ReviewIssue(code="unverifiable_claims", stage="matching")
    assert item.matching_reasons[0].level == "strong"
    assert item.matching_reasons[0].profile_source_quotes[0].document_id == "resume"


def test_several_valid_quotes_preserve_original_lines_and_do_not_fail_review() -> None:
    lines = [f"  Python project {i}: built a dashboard.  " for i in range(7)]

    def change(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            response["jobs"][0]["matches"][0]["profile_quote_ids"] = [f"p{i}" for i in range(7)]

    item = assess(
        ReplayProvider(change), [job("many-quotes")], documents={"resume": "\n".join(lines)}
    ).jobs[0]
    assert item.analysis_status == "complete"
    assert [q.excerpt for q in item.matching_reasons[0].profile_source_quotes] == lines


def test_resume_detail_survives_without_a_duplicate_extracted_profile_fact() -> None:
    quote = "Led a team of five to deliver a Python dashboard."
    applicant = profile()
    applicant.projects = []

    def change(task: str, response: dict[str, Any]) -> None:
        if task == "matching":
            row = response["jobs"][0]
            row["matches"][0].update(
                profile_fact_ids=[],
                profile_quote_ids=["p0"],
                explanation="You led a five-person team building a Python dashboard.",
            )
            row["dimensions"] = [
                {
                    "id": "responsibilities",
                    "status": "assessed",
                    "score": 75,
                    "requirement_ids": ["python"],
                    "explanation": "Your dashboard delivery involved team leadership.",
                }
            ]

    item = assess(
        ReplayProvider(change), [job("resume-detail")], applicant, {"resume": quote}
    ).jobs[0]
    assert item.analysis_status == "complete"
    assert item.matching_reasons[0].profile_source_quotes[0].excerpt == quote
    assert item.match_score is not None
    assert item.match_score.dimensions[1].score == 75
    assert item.review_issue is None


def test_related_projects_do_not_become_employment_duration_claims() -> None:
    applicant = profile()
    applicant.internships = ["Python developer, January 2024 to December 2024"]
    candidate = job("senior")
    candidate.description = "Python required. 8 years of experience required."
    candidate.source_documents[0].text = candidate.description

    def change(task: str, response: dict[str, Any]) -> None:
        row = response["jobs"][0]
        if task == "jd_analysis":
            row["requirements"][0].update(
                text="8 years of experience required",
                category="experience",
                minimum_experience_months=96,
                source_quotes=[
                    {"document_id": "doc-senior", "excerpt": "8 years of experience required."}
                ],
            )
        else:
            row.update(
                recommendation_fit="unlikely",
                recommendation_reason="Your work and projects are relevant, but the role requires eight years of employment.",
            )
            row["matches"][0].update(
                level="partial",
                profile_fact_ids=["internships:0", "projects:0"],
                profile_quote_ids=["p0", "p1"],
                experience_months=12,
            )

    item = assess(
        ReplayProvider(change),
        [candidate],
        applicant,
        {"resume": "Python developer, January 2024 to December 2024\nBuilt a Python dashboard."},
    ).jobs[0]
    assert item.analysis_status == "complete"
    assert item.recommendation_fit == "unlikely"
    assert item.matching_reasons[0].level == "partial"
    assert {q.excerpt for q in item.matching_reasons[0].profile_source_quotes} == {
        "Python developer, January 2024 to December 2024",
        "Built a Python dashboard.",
    }
    assert item.review_issue is None


def test_summary_and_metadata_cannot_be_presented_as_a_full_listing_review() -> None:
    candidate = job("summary")
    candidate.description_is_excerpt = True
    candidate.source_documents[0].is_excerpt = True
    candidate.source_documents.append(
        SourceDocument(
            document_id="job:summary:metadata",
            source=candidate.source,
            source_url=candidate.source_url,
            fetched_at=NOW,
            text="Data Intern\nHong Kong\ninternship",
        )
    )

    item = assess(ReplayProvider(), [candidate]).jobs[0]
    assert item.analysis_status == "partial"
    assert item.display_status(active=False) == "summary_reviewed"
    assert item.recommendation_reason
    assert "listing_incomplete" in {notice.code for notice in item.notices}
    assert "analysis_partial" not in {notice.code for notice in item.notices}
    full = job("full")
    full_item = assess(ReplayProvider(), [full]).jobs[0]
    assert full_item.display_status(active=False) == "reviewed"


def test_several_job_quotes_do_not_discard_the_extraction_batch() -> None:
    lines = [f"Python task {index}." for index in range(8)]
    detailed = job("many-job-quotes")
    detailed.description = "\n".join(lines)
    detailed.source_documents[0].text = detailed.description

    def change(task: str, response: dict[str, Any]) -> None:
        if task == "jd_analysis":
            for row in response["jobs"]:
                if row["job_id"] == detailed.job_id:
                    row["requirements"][0]["source_quotes"] = [
                        {"document_id": "doc-many-job-quotes", "excerpt": line} for line in lines
                    ]

    result = assess(ReplayProvider(change), [detailed, job("sibling")])
    items = {item.job.job_id: item for item in result.jobs}
    assert items["sibling"].analysis_status == "complete"
    assert items[detailed.job_id].analysis_status == "complete"
    assert [
        q.excerpt for q in items[detailed.job_id].matching_reasons[0].job_source_quotes
    ] == lines


def test_summary_uses_compact_schema_and_has_no_scores_or_preparation_plan() -> None:
    from jobscout.services.review_response import SummaryReviewResponse

    schemas: dict[str, type[Any]] = {}

    class RecordingProvider(ReplayProvider):
        async def structured(
            self,
            schema: type[Any],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> Any:
            import json

            payload = json.loads(messages[-1]["content"])
            if payload["task"] == "matching":
                schemas[payload["jobs"][0]["job_id"]] = schema
            return await super().structured(schema, messages, deadline=deadline)

    summary = job("summary")
    summary.description_is_excerpt = True
    summary.source_documents[0].is_excerpt = True
    result = assess(RecordingProvider(), [summary, job("full")])
    items = {item.job.job_id: item for item in result.jobs}
    assert schemas["summary"] is SummaryReviewResponse
    assert "dimensions" not in schemas["summary"].model_json_schema()["properties"]
    assert "preparation_suggestions" not in schemas["summary"].model_json_schema()["properties"]
    assert "dimensions" in schemas["full"].model_json_schema()["properties"]
    assert items["summary"].match_score is None
    assert items["summary"].preparation_suggestions == []
    assert items["summary"].matching_reasons[0].level == "strong"
    assert items["full"].analysis_status == "complete"
    assert items["full"].match_score is not None


def test_review_keeps_every_requirement_accepted_by_job_extraction() -> None:
    requirements = [f"Python task {index}" for index in range(30)]
    detailed = job("many-requirements")
    detailed.description = "\n".join(requirements)
    detailed.source_documents[0].text = detailed.description

    def change(task: str, response: dict[str, Any]) -> None:
        row = response["jobs"][0]
        if task == "jd_analysis":
            row["requirements"] = [
                {
                    "requirement_id": f"task-{index}",
                    "text": text,
                    "category": "skill",
                    "source_quotes": [{"document_id": "doc-many-requirements", "excerpt": text}],
                }
                for index, text in enumerate(requirements)
            ]
        else:
            row["dimensions"] = [
                {
                    "id": "skills",
                    "status": "assessed",
                    "score": 75,
                    "requirement_ids": [f"task-{index}" for index in range(30)],
                    "explanation": "Your Python dashboard work applies to these tasks.",
                }
            ]

    item = assess(ReplayProvider(change), [detailed]).jobs[0]
    assert item.analysis_status == "complete"
    assert [reason.requirement for reason in item.matching_reasons] == requirements
    assert item.match_score is not None
    skills = next(
        dimension for dimension in item.match_score.dimensions if dimension.id == "skills"
    )
    assert skills.requirement_ids == [f"task-{index}" for index in range(30)]
    assert skills.score == 75


def test_summary_with_no_explicit_requirements_keeps_the_preliminary_advice() -> None:
    reason = "The title is in your chosen field. The summary does not describe the work; check the duties and seniority."

    def change(task: str, response: dict[str, Any]) -> None:
        row = response["jobs"][0]
        if task == "jd_analysis":
            row["requirements"] = []
        else:
            row.update(recommendation_fit="unknown", recommendation_reason=reason)

    summary = job("title-only")
    summary.description = ""
    summary.source_documents = []
    item = assess(ReplayProvider(change), [summary]).jobs[0]
    assert item.display_status(active=False) == "summary_reviewed"
    assert item.recommendation_fit == "unknown"
    assert item.recommendation_reason == reason
    assert item.matching_reasons == []
    assert item.match_score is None
    assert item.review_issue is None


def test_a_usable_summary_survives_a_failed_retry() -> None:
    # The assessment service returns the failure; search owns the retained previous result.
    async def scenario() -> None:
        from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
        from tests.test_search_agent import Assessment, ScriptedProvider, SnapshotSearch, query, run

        class RetryAssessment(Assessment):
            diagnostics: dict[str, Any] = {}

            async def assess(self, *args: Any, **kwargs: Any) -> RecommendationResult:
                from jobscout.services.job_assessment_service import AssessmentDiagnostic

                result = await super().assess(*args, **kwargs)
                row = result.jobs[0]
                self.diagnostics[row.job.job_id] = AssessmentDiagnostic(
                    code="model_failure", stage="matching", detail="model_timeout", retryable=True
                )
                result.jobs = [
                    row.model_copy(
                        update={
                            "analysis_status": "partial",
                            "recommendation_reason": "The Python work is relevant.",
                        }
                    )
                    if len(self.feedback) == 1
                    else RecommendationItem(
                        job=row.job,
                        analysis_status="unavailable",
                        review_issue=ReviewIssue(code="timeout", stage="matching"),
                    )
                ]
                return result

        provider = ScriptedProvider(
            [
                lambda _: query(),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda _: ("finish_search", {"reason": "results_ready"}),
            ]
        )
        assessment = RetryAssessment()
        result = await run(provider, SnapshotSearch(1), assessment)
        assert len(assessment.feedback) == 2
        item = result["recommendation"].jobs[0]
        assert item.analysis_status == "partial"
        assert item.recommendation_reason == "The Python work is relevant."
        assert item.review_issue == ReviewIssue(code="timeout", stage="matching")

    asyncio.run(scenario())
