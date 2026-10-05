"""Tests for normalization, duplicate merging, and freshness status.

All inputs are fixed, self-made Mock records (plus the shared
``data/mock_jobs.json`` sample); no external service is called.

Coverage follows the ten acceptance scenarios: normal conversion, cross-source
fields, absent salary, evidence-based JD extraction, duplicate merging, distinct
seniority, expired/unknown status, diagnostics, and empty input. Group 4 maps
website-specific field names to common top-level keys before calling Group 5.
New acceptance tests remain ordinary tests so unsupported behavior is visible.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jobscout.schemas.job import FreshnessStatus
from jobscout.services.job_processing_service import process_jobs

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def make_raw(**overrides: Any) -> dict[str, Any]:
    """Build a valid raw retrieval record; override fields per test case."""
    record: dict[str, Any] = {
        "job_id": "raw-1",
        "source": "jobsdb",
        "source_url": "https://jobsdb.example.com/post/1",
        "title": "Data Analyst",
        "company": "Acme Ltd",
        "location": "Hong Kong",
        "salary": "HKD 20,000/month",
        "target_direction": "Data Analyst",
        "responsibilities": ["Build dashboards"],
        "required_skills": ["SQL", "Python"],
        "posted_at": "2026-09-20T00:00:00Z",
        "expiry_at": "2026-10-20T00:00:00Z",
        "freshness_status": "unknown",
        "fetched_at": "2026-09-28T08:00:00Z",
        "source_links": ["https://jobsdb.example.com/post/1"],
    }
    record.update(overrides)
    return record


def test_normalizes_complete_record_and_preserves_provenance() -> None:
    result = process_jobs([make_raw()], now=NOW)

    assert result.warnings == []
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_id == "raw-1"
    assert job.title == "Data Analyst"
    assert job.company == "Acme Ltd"
    assert job.location == "Hong Kong"
    assert job.salary == "HKD 20,000/month"
    assert job.target_direction == "Data Analyst"
    assert job.responsibilities == ["Build dashboards"]
    assert job.required_skills == ["SQL", "Python"]
    assert job.posted_at == datetime(2026, 9, 20, tzinfo=UTC)
    assert job.expiry_at == datetime(2026, 10, 20, tzinfo=UTC)
    assert job.freshness_status is FreshnessStatus.ACTIVE  # expiry_at is in the future
    assert job.source_url == "https://jobsdb.example.com/post/1"
    assert job.source_links == ["https://jobsdb.example.com/post/1"]
    assert job.fetched_at == datetime(2026, 9, 28, 8, 0, tzinfo=UTC)

    # Serialization uses the frozen pydantic contract (no custom to_dict).
    dumped = job.model_dump(mode="json")
    assert dumped["fetched_at"] is not None
    assert datetime.fromisoformat(dumped["fetched_at"]) == job.fetched_at
    assert dumped["freshness_status"] == "active"
    assert dumped["salary"] == "HKD 20,000/month"


def test_result_supports_tuple_unpacking() -> None:
    jobs, warnings = process_jobs([make_raw()], now=NOW)

    assert len(jobs) == 1
    assert jobs[0].job_id == "raw-1"
    assert warnings == []


def test_empty_input_returns_empty_result() -> None:
    jobs, warnings = process_jobs([], now=NOW)

    assert jobs == []
    assert warnings == []


def test_whitespace_is_normalized_in_text_fields() -> None:
    result = process_jobs([make_raw(title="  Data   Analyst  ", company="\nAcme   Ltd\t")], now=NOW)

    job = result.jobs[0]
    assert job.title == "Data Analyst"
    assert job.company == "Acme Ltd"


@pytest.mark.parametrize(
    ("source", "raw_payload"),
    [
        pytest.param(
            "zhaopin",
            {"name": "Data Analyst", "companyName": "Acme Ltd", "workCity": "Hong Kong"},
            id="zhaopin-native-fields",
        ),
        pytest.param(
            "liepin",
            {
                "job": {"title": "Data Analyst", "dq": "Hong Kong"},
                "comp": {"compName": "Acme Ltd"},
            },
            id="liepin-native-fields",
        ),
        pytest.param(
            "jobsdb",
            {
                "title": "Data Analyst",
                "advertiser": {"description": "Acme Ltd"},
                "locations": [{"label": "Hong Kong"}],
            },
            id="jobsdb-native-fields",
        ),
    ],
)
def test_normalizes_group4_records_with_different_native_payloads(
    source: str, raw_payload: dict[str, Any]
) -> None:
    # Mirror Group 4's RawJob output, without Group 5-only helper defaults.
    # Native field mapping belongs to retrieval; raw_payload remains diagnostic.
    record: dict[str, Any] = {
        "source": source,
        "source_job_id": "native-1",
        "source_url": f"https://{source}.example.com/jobs/native-1",
        "fetched_at": "2026-09-28T08:00:00Z",
        "target_direction": "Data Analyst",
        "title": "  Data   Analyst  ",
        "company": " Acme Ltd ",
        "location": " Hong Kong ",
        "salary": "HKD 20,000/month",
        "description": "Responsibilities:\n- Build dashboards\nRequirements:\n- SQL\n",
        "posted_at": "2026-09-20T00:00:00Z",
        "expiry_at": "2026-10-20T00:00:00Z",
        "raw_payload": raw_payload,
    }

    result = process_jobs([record], now=NOW)

    assert result.warnings == []
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_id
    assert job.source == source
    assert (job.title, job.company, job.location) == ("Data Analyst", "Acme Ltd", "Hong Kong")
    assert job.salary == "HKD 20,000/month"
    assert job.target_direction == "Data Analyst"
    assert job.responsibilities == ["Build dashboards"]
    assert job.required_skills == ["SQL"]
    assert job.source_url == record["source_url"]
    assert job.source_links == [record["source_url"]]
    assert job.fetched_at == datetime(2026, 9, 28, 8, tzinfo=UTC)
    assert job.posted_at == datetime(2026, 9, 20, tzinfo=UTC)
    assert job.expiry_at == datetime(2026, 10, 20, tzinfo=UTC)
    assert job.freshness_status is FreshnessStatus.ACTIVE


def test_parses_responsibilities_and_skills_from_description() -> None:
    description = (
        "We are hiring.\n"
        "Responsibilities:\n"
        "- Build data pipelines\n"
        "- Maintain BI dashboards\n"
        "Requirements:\n"
        "- SQL\n"
        "- Python\n"
    )
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.responsibilities == ["Build data pipelines", "Maintain BI dashboards"]
    assert job.required_skills == ["SQL", "Python"]


def test_lexicon_fallback_when_description_has_no_skills_section() -> None:
    description = "The ideal candidate has strong Python, SQL and Tableau experience."
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.required_skills == ["Python", "SQL", "Tableau"]


def test_does_not_invent_responsibilities_or_skills_from_unrelated_description() -> None:
    record = make_raw(
        responsibilities=[],
        required_skills=[],
        description="We offer a friendly workplace and flexible hours.",
    )

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    assert result.jobs[0].responsibilities == []
    assert result.jobs[0].required_skills == []
    assert any("no responsibilities or required skills" in warning for warning in result.warnings)


def test_jd_extraction_keeps_benefits_out_of_responsibilities_and_skills() -> None:
    description = (
        "Responsibilities:\n- Maintain reports\n"
        "Requirements:\n- SQL\n"
        "Benefits:\n- Free lunch\n- Optional Python training\n"
    )
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.responsibilities == ["Maintain reports"]
    assert job.required_skills == ["SQL"]


def test_parses_chinese_responsibilities_and_skills_from_description() -> None:
    description = "岗位职责：\n- 维护业务报表\n任职要求：\n- 熟悉 SQL\n- 熟悉 Python\n"
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.responsibilities == ["维护业务报表"]
    assert job.required_skills == ["熟悉 SQL", "熟悉 Python"]


def test_parses_html_description_and_preserves_section_boundaries() -> None:
    description = (
        "<h2>Responsibilities:</h2>"
        "<ul><li>Build dashboards &amp; reports</li><li>Maintain data pipelines</li></ul>"
        "<h2>Requirements:</h2><ul><li>SQL</li><li>Python</li></ul>"
        "<h2>Benefits:</h2><p>Free lunch</p>"
    )
    record = make_raw(responsibilities=[], required_skills=[], description=description)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.responsibilities == ["Build dashboards & reports", "Maintain data pipelines"]
    assert job.required_skills == ["SQL", "Python"]


@pytest.mark.parametrize(
    "field",
    ["title", "company", "source_url", "location", "target_direction", "fetched_at"],
)
def test_drops_records_missing_required_fields(field: str) -> None:
    result = process_jobs([make_raw(job_id="bad", **{field: None}), make_raw(job_id="ok")], now=NOW)

    assert [job.job_id for job in result.jobs] == ["ok"]
    assert any("bad" in warning and field in warning for warning in result.warnings)


def test_drops_record_with_unparseable_fetched_at() -> None:
    result = process_jobs([make_raw(job_id="bad", fetched_at="not-a-date")], now=NOW)

    assert result.jobs == []
    assert any("bad" in warning and "fetched_at" in warning for warning in result.warnings)


def test_missing_optional_fields_keep_job_with_warnings() -> None:
    record = make_raw(salary=None, posted_at=None, expiry_at=None)

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.salary is None
    assert job.posted_at is None
    assert job.expiry_at is None
    assert any("missing salary" in warning for warning in result.warnings)
    assert any("missing posted_at" in warning for warning in result.warnings)
    assert any("missing expiry_at" in warning for warning in result.warnings)


@pytest.mark.parametrize("salary", [None, "", "   "], ids=["missing-key", "empty", "blank"])
def test_missing_or_blank_salary_never_becomes_zero(salary: str | None) -> None:
    record = make_raw(salary=salary)
    if salary is None:
        # A missing key is a separate input case from the existing salary=None test.
        del record["salary"]

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    assert result.jobs[0].salary is None
    assert any("salary" in warning for warning in result.warnings)


@pytest.mark.parametrize("field", ["posted_at", "expiry_at"])
def test_unparseable_optional_dates_keep_record_and_warn(field: str) -> None:
    record = make_raw(job_id="bad-date", **{field: "not-a-date"})

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert getattr(job, field) is None
    assert any("bad-date" in warning and field in warning for warning in result.warnings)
    if field == "expiry_at":
        assert job.freshness_status is FreshnessStatus.UNKNOWN
    else:
        assert job.expiry_at == datetime(2026, 10, 20, tzinfo=UTC)
        assert job.freshness_status is FreshnessStatus.ACTIVE


def test_missing_source_falls_back_to_unknown_with_warning() -> None:
    result = process_jobs([make_raw(source=None)], now=NOW)

    job = result.jobs[0]
    assert job.source == "unknown"
    assert any("missing source" in warning for warning in result.warnings)


def test_warns_when_no_responsibilities_or_skills_extracted() -> None:
    record = make_raw(responsibilities=[], required_skills=[])

    result = process_jobs([record], now=NOW)

    job = result.jobs[0]
    assert job.responsibilities == []
    assert job.required_skills == []
    assert any("no responsibilities or required skills" in warning for warning in result.warnings)


def test_merges_cross_source_duplicates_and_keeps_all_links() -> None:
    first = make_raw(
        job_id="a",
        source="jobsdb",
        source_url="https://jobsdb.example.com/post/1",
        source_links=["https://jobsdb.example.com/post/1"],
        responsibilities=["Build dashboards"],
        required_skills=["SQL"],
        fetched_at="2026-09-27T08:00:00Z",
    )
    second = make_raw(
        job_id="b",
        source="linkedin",
        source_url="https://linkedin.example.com/jobs/99",
        source_links=["https://linkedin.example.com/jobs/99"],
        responsibilities=["Maintain pipelines", "build dashboards"],
        required_skills=["Python", "sql"],
        fetched_at="2026-09-28T09:00:00Z",
    )

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "jobsdb, linkedin"
    assert job.source_links == [
        "https://jobsdb.example.com/post/1",
        "https://linkedin.example.com/jobs/99",
    ]
    assert job.required_skills == ["SQL", "Python"]
    assert job.responsibilities == ["Build dashboards", "Maintain pipelines"]
    assert job.fetched_at == datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def test_dedup_key_ignores_case_and_punctuation() -> None:
    first = make_raw(job_id="a", company="Acme, Ltd.", title="Data Analyst!")
    second = make_raw(job_id="b", company="acme ltd", title="data analyst")

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1


def test_does_not_merge_different_locations_or_titles() -> None:
    other_location = make_raw(job_id="b", location="Singapore")
    other_title = make_raw(job_id="c", title="Data Engineer")

    result = process_jobs([make_raw(job_id="a"), other_location, other_title], now=NOW)

    assert len(result.jobs) == 3


@pytest.mark.parametrize("other_title", ["Senior Data Analyst", "Data Analyst Intern"])
def test_does_not_merge_similar_titles_with_different_seniority(other_title: str) -> None:
    first = make_raw(job_id="regular")
    second = make_raw(job_id="other-level", title=other_title)

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 2
    assert {job.title for job in result.jobs} == {"Data Analyst", other_title}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"company": "乙公司"}, id="different-company"),
        pytest.param({"title": "商业分析实习生"}, id="different-title"),
        pytest.param({"location": "北京"}, id="different-location"),
        pytest.param({"title": "高级数据分析实习生"}, id="different-seniority"),
        pytest.param(
            {"company": "乙公司", "title": "商业分析实习生", "location": "北京"},
            id="all-fields-differ",
        ),
    ],
)
def test_does_not_merge_distinct_chinese_jobs(overrides: dict[str, str]) -> None:
    first = make_raw(
        job_id="cn-1",
        company="甲公司",
        title="数据分析实习生",
        location="上海",
        source_url="https://example.com/cn-1",
        source_links=["https://example.com/cn-1"],
    )
    second = {
        **first,
        **overrides,
        "job_id": "cn-2",
        "source_url": "https://example.com/cn-2",
        "source_links": ["https://example.com/cn-2"],
    }

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 2
    jobs_by_id = {job.job_id: job for job in result.jobs}
    assert set(jobs_by_id) == {"cn-1", "cn-2"}
    for raw in (first, second):
        job = jobs_by_id[raw["job_id"]]
        assert (job.company, job.title, job.location) == (
            raw["company"],
            raw["title"],
            raw["location"],
        )
        assert job.source_links == [raw["source_url"]]


def test_merges_same_chinese_job_across_sources_and_keeps_links() -> None:
    first = make_raw(
        job_id="cn-a",
        source="zhaopin",
        company="甲公司",
        title="数据分析实习生",
        location="上海",
        source_url="https://zhaopin.example.com/cn-a",
        source_links=["https://zhaopin.example.com/cn-a"],
    )
    second = {
        **first,
        "job_id": "cn-b",
        "source": "liepin",
        "source_url": "https://liepin.example.com/cn-b",
        "source_links": ["https://liepin.example.com/cn-b"],
    }

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert (job.company, job.title, job.location) == ("甲公司", "数据分析实习生", "上海")
    assert job.source == "zhaopin, liepin"
    assert job.source_links == [first["source_url"], second["source_url"]]


def test_does_not_merge_different_chinese_jobs() -> None:
    first = make_raw(job_id="a", company="腾讯科技", title="数据分析师", location="深圳")
    second = make_raw(job_id="b", company="阿里巴巴", title="产品经理", location="杭州")

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 2


def test_merges_chinese_duplicates_across_sources_and_keeps_all_links() -> None:
    first = make_raw(
        job_id="a",
        source="zhaopin",
        source_url="https://zhaopin.example.com/post/1",
        source_links=["https://zhaopin.example.com/post/1"],
        company="腾讯科技",
        title="数据分析师",
        location="深圳",
    )
    second = make_raw(
        job_id="b",
        source="liepin",
        source_url="https://liepin.example.com/job/9",
        source_links=["https://liepin.example.com/job/9"],
        company="腾讯科技",
        title="数据分析师",
        location="深圳",
    )

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "zhaopin, liepin"
    assert job.source_links == [
        "https://zhaopin.example.com/post/1",
        "https://liepin.example.com/job/9",
    ]


def test_does_not_merge_chinese_titles_sharing_latin_prefix() -> None:
    backend = make_raw(job_id="a", title="Java后端开发工程师")
    frontend = make_raw(job_id="b", title="Java前端开发工程师")

    result = process_jobs([backend, frontend], now=NOW)

    assert len(result.jobs) == 2


def test_generated_ids_differ_for_distinct_chinese_jobs() -> None:
    first = make_raw(job_id=None, company="腾讯科技", title="数据分析师", location="深圳")
    second = make_raw(job_id=None, company="阿里巴巴", title="产品经理", location="杭州")

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 2
    ids = {job.job_id for job in result.jobs}
    assert all(job_id.startswith("gen-") for job_id in ids)
    assert len(ids) == 2


def test_freshness_expired_when_expiry_passed() -> None:
    job = process_jobs([make_raw(expiry_at="2026-09-01T00:00:00Z")], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


def test_freshness_active_when_expiry_in_future() -> None:
    job = process_jobs([make_raw(expiry_at="2026-12-31T00:00:00Z")], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.ACTIVE


def test_freshness_honors_explicit_source_status_case_insensitively() -> None:
    record = make_raw(expiry_at=None, freshness_status="Expired")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


def test_freshness_unknown_without_evidence() -> None:
    record = make_raw(expiry_at=None, freshness_status=None)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.UNKNOWN


def test_posted_at_alone_never_proves_active() -> None:
    record = make_raw(expiry_at=None, freshness_status=None, posted_at="2020-01-01T00:00:00Z")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.UNKNOWN


def test_expiry_beats_explicit_active_status() -> None:
    record = make_raw(expiry_at="2026-09-01T00:00:00Z", freshness_status="active")

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.EXPIRED


@pytest.mark.parametrize(
    ("expiry_at", "source_status", "expected_status"),
    [
        pytest.param(
            "2026-09-01T00:00:00Z", "active", FreshnessStatus.EXPIRED, id="past-but-active"
        ),
        pytest.param(
            "2026-10-20T00:00:00Z", "expired", FreshnessStatus.ACTIVE, id="future-but-expired"
        ),
    ],
)
def test_warns_when_expiry_conflicts_with_explicit_source_status(
    expiry_at: str, source_status: str, expected_status: FreshnessStatus
) -> None:
    record = make_raw(expiry_at=expiry_at, freshness_status=source_status)

    result = process_jobs([record], now=NOW)

    assert len(result.jobs) == 1
    # Keep the documented expiry-first rule; acceptance additionally needs a warning.
    assert result.jobs[0].freshness_status is expected_status
    assert any(
        "raw-1" in warning and "expiry_at" in warning and "freshness_status" in warning
        for warning in result.warnings
    )


def test_conflicting_duplicate_statuses_are_expired_and_reported() -> None:
    first = make_raw(job_id="active-source", expiry_at=None, freshness_status="active")
    second = make_raw(job_id="expired-source", expiry_at=None, freshness_status="expired")

    result = process_jobs([first, second], now=NOW)

    assert len(result.jobs) == 1
    assert result.jobs[0].freshness_status is FreshnessStatus.EXPIRED
    # Missing-date warnings do not count as a status-conflict warning.
    assert any("freshness_status" in warning for warning in result.warnings)


@pytest.mark.parametrize("source_status", [None, "unknown", "not-a-status"])
def test_unreliable_source_status_without_dates_stays_unknown(source_status: str | None) -> None:
    record = make_raw(posted_at=None, expiry_at=None, freshness_status=source_status)

    job = process_jobs([record], now=NOW).jobs[0]

    assert job.freshness_status is FreshnessStatus.UNKNOWN


def test_generates_stable_job_id_when_missing() -> None:
    first = process_jobs([make_raw(job_id=None)], now=NOW).jobs[0]
    second = process_jobs([make_raw(job_id=None)], now=NOW).jobs[0]

    assert first.job_id.startswith("gen-")
    assert first.job_id == second.job_id


def test_shared_mock_sample_stays_unknown_and_keeps_provenance() -> None:
    raw_jobs: list[dict[str, Any]] = json.loads((DATA_DIR / "mock_jobs.json").read_text("utf-8"))

    result = process_jobs(raw_jobs, now=NOW)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.freshness_status is FreshnessStatus.UNKNOWN  # never faked as active
    assert job.source_url == "https://example.com/jobs/mock-001"
    assert job.source_links == ["https://example.com/jobs/mock-001"]
    assert job.fetched_at == datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    assert job.required_skills == ["SQL", "Python"]
    # Optional fields the sample lacks stay None and are reported, not fabricated.
    assert job.salary is None
    assert job.posted_at is None
    assert job.expiry_at is None
    assert any("missing salary" in warning for warning in result.warnings)
    assert any("missing posted_at" in warning for warning in result.warnings)
    assert any("missing expiry_at" in warning for warning in result.warnings)
