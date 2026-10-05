"""Regressions at the boundary between model meanings and deterministic contracts."""

import asyncio
from typing import Any

import pytest

from jobscout.schemas.conversation import MatchingReason
from jobscout.schemas.profile import WorkArrangement
from jobscout.services.condition_service import ConditionService
from jobscout.services.conversation_service import ProfileChange, apply_changes, missing_fields
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.job_retrieval.models import SearchResult, SourceOutcome, workflow_error
from jobscout.services.ranking import evidence_score
from jobscout.services.replay_service import ReplayProvider
from jobscout.services.search_agent import SearchAgent
from tests.test_conditions_and_locations import MeaningProvider
from tests.test_job_assessment_service import profile as assessment_profile
from tests.test_job_processing_service import make_raw
from tests.test_search_agent import Assessment, SnapshotSearch, profile, raw, run
from tests.test_semantic_evidence import evaluate


@pytest.mark.parametrize(
    ("text", "meaning", "expected"),
    [
        ("只考虑居家办公", {"work_modes": ["remote"]}, "remote"),
        ("遠端或每週回辦公室兩天", {"work_modes": ["remote", "hybrid"]}, None),
        ("不想每天到公司", {"excluded_work_modes": ["onsite"]}, None),
        ("怎样办公都可以", {"work_mode_unrestricted": True}, None),
    ],
)
def test_model_work_arrangement_is_used_for_source_requests(
    text: str, meaning: dict[str, Any], expected: str | None
) -> None:
    async def scenario() -> None:
        applicant = profile(5)
        applicant.preferences.work_mode = text
        provider = MeaningProvider(
            {
                "locations": {"included": ["Hong Kong"]},
                "employment": {"included": ["internship"]},
                **meaning,
            }
        )
        interpreted = await ConditionService(provider).resolve(applicant)
        assert provider.payloads[0]["work_mode"] == text
        assert interpreted.preferences.work_mode == text
        assert interpreted.preferences.work_arrangement.raw_text == text
        search = SnapshotSearch(5)
        result = await run(ReplayProvider(), search, Assessment(), interpreted)
        assert result["stop_reason"] == "target_reached"
        assert search.requests[0].work_mode == expected
        assert interpreted.conflicts == []

    asyncio.run(scenario())


def test_uncertain_work_mode_requires_clarification_and_clear_discards_old_meaning() -> None:
    applicant = profile()
    applicant.preferences.work_mode = "视情况决定驻场安排"
    provider = MeaningProvider(
        {
            "locations": {"included": ["Hong Kong"]},
            "employment": {"included": ["internship"]},
            "work_mode_uncertain": True,
        }
    )
    result = asyncio.run(ConditionService(provider).resolve(applicant))
    assert "preferences.work_mode" in missing_fields(result)
    cleared = apply_changes(result, [ProfileChange(field="preferences.work_mode", value=None)])
    provider.meaning["work_mode_uncertain"] = False
    cleared = asyncio.run(ConditionService(provider).resolve(cleared))
    assert cleared.preferences.work_arrangement == WorkArrangement()
    assert "preferences.work_mode" not in cleared.conflicts


def test_dedup_preserves_language_symbols_and_merges_only_equivalent_spelling() -> None:
    rows = [
        make_raw(job_id="cpp", title="C++ Developer", source_url="https://jobs.test/cpp"),
        make_raw(job_id="csharp", title="C# Developer", source_url="https://jobs.test/csharp"),
        make_raw(job_id="cpp-copy", title="Ｃ＋＋  Developer", source_url="https://jobs.test/copy"),
    ]
    result = process_jobs(rows)
    by_title = {job.title: job for job in result.jobs}
    assert set(by_title) == {"C++ Developer", "C# Developer"}
    assert by_title["C++ Developer"].job_id != by_title["C# Developer"].job_id
    assert "https://jobs.test/copy" in by_title["C++ Developer"].source_links
    assert "https://jobs.test/csharp" not in by_title["C++ Developer"].source_links


def test_profile_edits_keep_compound_facts_intact() -> None:
    facts = ["BSc, Computer Science", "Designed API; tested CI/CD | deployment"]
    applicant = apply_changes(profile(), [ProfileChange(field="education", value=facts)])
    assert applicant.education == facts
    applicant = apply_changes(
        applicant,
        [ProfileChange(field="target_directions", value="Engineer, AI/ML\nUI/UX Designer")],
    )
    assert applicant.target_directions == ["Engineer, AI/ML", "UI/UX Designer"]


@pytest.mark.parametrize(
    "qualification",
    [
        "Higher Diploma in Mechanical Engineering",
        "Associate Degree in Applied Science",
        "Registered electrical worker qualification",
        "ACCA professional qualification",
    ],
)
def test_open_qualification_descriptions_can_be_supported(qualification: str) -> None:
    applicant = assessment_profile()
    applicant.education = [qualification]
    result = evaluate(
        {
            "text": f"Required: {qualification}",
            "category": "education",
            "qualification_options": [qualification],
        },
        {
            "profile_fact_ids": ["education:0"],
            "qualifications": [qualification],
            "qualification_relation": "meets",
        },
        applicant,
        qualification,
    )
    assert [item.job.job_id for item in result.jobs] == ["semantic"]
    assert result.jobs[0].matching_reasons[0].profile_source_quotes[0].excerpt == qualification


@pytest.mark.parametrize("qualification", ["MSc in Engineering (in progress)", "PhD in Music"])
def test_degree_status_or_unrelated_higher_degree_cannot_claim_strong_match(
    qualification: str,
) -> None:
    applicant = assessment_profile()
    applicant.education = [qualification]
    result = evaluate(
        {
            "text": "Completed MSc in Engineering required",
            "category": "education",
            "qualification_options": ["Completed MSc in Engineering"],
        },
        {
            "profile_fact_ids": ["education:0"],
            "qualifications": [qualification],
            "qualification_relation": "does_not_meet",
        },
        applicant,
        qualification,
    )
    assert result.jobs == result.pending_jobs == []


def test_global_ranking_does_not_reward_longer_lists_of_requirements() -> None:
    def reasons(level: str, count: int) -> list[MatchingReason]:
        return [
            MatchingReason.model_validate(
                {"requirement": f"r{index}", "level": level, "explanation": "Evidence"}
            )
            for index in range(count)
        ]

    from jobscout.schemas.recommendation import RecommendationItem
    from tests.test_job_assessment_service import job

    short = RecommendationItem(
        job=job("short", direction="Data Analyst"), matching_reasons=reasons("strong", 2)
    )
    long = RecommendationItem(
        job=job("long", direction="Data Analyst"), matching_reasons=reasons("partial", 20)
    )
    agent = SearchAgent(ReplayProvider(), SnapshotSearch(), Assessment())
    agent.profile, agent.target = profile(), 10
    assert evidence_score(reasons("strong", 2)) == evidence_score(reasons("strong", 20))
    assert [row.job.job_id for row in agent.ranked([long, short])] == ["short", "long"]


@pytest.mark.parametrize("initial", ["duplicates", "empty", "timeout"])
def test_search_continues_after_duplicates_empty_query_or_transient_failure(initial: str) -> None:
    class RecoveringSearch(SnapshotSearch):
        async def search_many_async(self, requests: Any, *, timeout: float = 60) -> SearchResult:
            self.requests.extend(requests)
            request = requests[0]
            if initial == "timeout" and len(self.requests) == 1:
                return SearchResult(
                    errors=[workflow_error("SEARCH_TIMEOUT", "Timed out")],
                    outcomes=[
                        SourceOutcome(
                            source="jobsdb", target_direction="Data Analyst", status="failed"
                        )
                    ],
                )
            if initial == "empty" and request.keywords == ["Data Analyst"]:
                rows = []
            elif initial == "duplicates" and request.page < 3:
                rows = [raw(0)]
            else:
                rows = [raw(index) for index in range(5)]
            return SearchResult(
                raw_jobs=rows,
                outcomes=[
                    SourceOutcome(
                        source="jobsdb",
                        target_direction="Data Analyst",
                        status="ok" if rows else "empty",
                        candidate_count=len(rows),
                        returned_count=len(rows),
                    )
                ],
            )

    async def scenario() -> None:
        search = RecoveringSearch()
        result = await run(ReplayProvider(), search, Assessment(), profile(5))
        assert result["stop_reason"] == "target_reached"
        assert {row.job.source_url for row in result["recommendation"].jobs} == {
            f"https://jobsdb.example/jobs/{index}" for index in range(5)
        }
        if initial == "duplicates":
            assert [request.page for request in search.requests] == [1, 2, 3]
        elif initial == "empty":
            assert search.requests[1].keywords != search.requests[0].keywords
        else:
            assert [request.page for request in search.requests] == [1, 1]

    asyncio.run(scenario())
