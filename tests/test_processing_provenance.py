"""Provenance, multi-direction deduplication and deterministic analysis selection."""

from copy import deepcopy
from datetime import UTC, datetime

from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.services.job_processing_service import process_jobs, select_balanced_candidates

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def raw(**updates: object) -> dict[str, object]:
    return {
        "source": "jobsdb",
        "source_url": "https://example.invalid/jobsdb/1",
        "title": "Data Analyst",
        "company": "Example",
        "location": "Hong Kong",
        "target_direction": "Data Analyst",
        "description": "SQL analytics",
        "fetched_at": NOW.isoformat(),
        "salary": "HKD 20,000",
        **updates,
    }


def test_exact_source_text_and_all_directions_survive_merge() -> None:
    original = [
        raw(description="SQL preview", description_is_excerpt=True),
        raw(
            source="liepin",
            source_url="https://example.invalid/liepin/2",
            target_direction="Business Analyst",
            description="<p>SQL requirements</p>\n<p>Build dashboards.</p>",
            employment_type="full-time",
        ),
        raw(
            description="SQL preview",
            description_is_excerpt=True,
            target_direction="Business Analyst",
        ),
    ]
    snapshot = deepcopy(original)
    job = process_jobs(original, now=NOW).jobs[0]
    assert original == snapshot
    assert job.target_directions == ["Data Analyst", "Business Analyst"]
    assert len(job.source_documents) == 2
    assert job.description == "SQL requirements\nBuild dashboards."
    assert not job.description_is_excerpt
    assert job.employment_type == "full-time"
    by_source = {document.source: document for document in job.source_documents}
    assert by_source["jobsdb"].text == "SQL preview" and by_source["jobsdb"].is_excerpt
    assert by_source["liepin"].text == original[1]["description"]
    assert by_source["liepin"].source_url == original[1]["source_url"]
    reversed_job = process_jobs(list(reversed(original)), now=NOW).jobs[0]
    assert reversed_job.job_id == job.job_id
    assert reversed_job.source_documents == job.source_documents
    assert reversed_job.description == job.description


def test_listing_and_detail_documents_retain_actual_fetch_times() -> None:
    job = process_jobs(
        [
            raw(
                description="Full detail SQL",
                raw_payload={
                    "listing_description": "Preview SQL",
                    "listing_fetched_at": "2026-09-30T12:00:00Z",
                    "detail_fetched_at": "2026-10-01T12:00:00Z",
                    "description_is_excerpt": False,
                },
            )
        ],
        now=NOW,
    ).jobs[0]
    assert len(job.source_documents) == 2
    detail = next(document for document in job.source_documents if not document.is_excerpt)
    preview = next(document for document in job.source_documents if document.is_excerpt)
    assert detail.fetched_at == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert preview.fetched_at == datetime(2026, 9, 30, 12, tzinfo=UTC)
    assert detail.document_id != preview.document_id


def test_existing_source_documents_are_not_reattributed_to_merged_source() -> None:
    original = process_jobs(
        [
            raw(),
            raw(
                source="liepin",
                source_url="https://example.invalid/2",
                description="Python projects",
            ),
        ],
        now=NOW,
    ).jobs[0]
    processed = process_jobs([original.model_dump()], now=NOW).jobs[0]
    assert processed.source_documents == original.source_documents
    assert processed.target_directions == original.target_directions


def test_conflicting_types_are_unknown_not_first_source_wins() -> None:
    result = process_jobs(
        [raw(employment_type="internship"), raw(employment_type="full-time")], now=NOW
    )
    assert result.jobs[0].employment_type is None
    assert any("Conflicting source employment types" in warning for warning in result.warnings)


def posting(identifier: str, direction: str, source: str, *, excerpt: bool = False) -> JobPosting:
    return JobPosting(
        job_id=identifier,
        title=identifier,
        company="Example",
        location="Hong Kong",
        target_direction=direction,
        target_directions=[direction],
        source=source,
        source_url=f"https://example.invalid/{identifier}",
        fetched_at=NOW,
        description="SQL analytics",
        description_is_excerpt=excerpt,
    )


def test_balanced_rotation_prefers_complete_and_is_input_order_independent() -> None:
    jobs = [
        posting("a-excerpt", "A", "one", excerpt=True),
        posting("z-complete", "A", "one"),
        posting("a-two", "A", "two"),
        posting("b-one", "B", "one"),
        posting("b-two", "B", "two"),
    ]
    selected = select_balanced_candidates(jobs, 4)
    assert [job.job_id for job in selected] == ["z-complete", "b-one", "a-two", "b-two"]
    assert select_balanced_candidates(list(reversed(jobs)), 4) == selected
    assert not select_balanced_candidates(jobs, 0)


def test_multiple_directions_sources_count_once_and_expired_are_excluded() -> None:
    jobs = [posting(str(index).zfill(2), "A" if index % 2 else "B", "one") for index in range(24)]
    jobs[0].target_directions = ["A", "B", "C"]
    jobs[0].source = "one, two"
    jobs[1].freshness_status = FreshnessStatus.EXPIRED
    jobs.append(jobs[0].model_copy())
    result = select_balanced_candidates(jobs)
    assert len(result) == 20
    assert len({job.job_id for job in result}) == 20
    assert jobs[1] not in result
    assert select_balanced_candidates(list(reversed(jobs))) == result
