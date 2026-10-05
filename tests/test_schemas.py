"""Tests for shared Pydantic schema contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import SearchOptions, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import SearchRequest
from jobscout.schemas.session import SessionCreateRequest


def make_job(job_id: str = "job-1") -> JobPosting:
    return JobPosting(
        job_id=job_id,
        source="mock",
        source_url="https://example.com/jobs/1",
        title="Data Analyst Intern",
        company="Example Co",
        location="Hong Kong",
        target_direction="data analyst",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize("group", ["jobs", "pending_jobs"])
def test_recommendation_result_limits_each_group_to_twenty(group: str) -> None:
    items = [RecommendationItem(job=make_job(f"job-{index}")) for index in range(21)]
    with pytest.raises(ValidationError) as error:
        RecommendationResult.model_validate(
            {
                "session_id": "session-1",
                "generated_at": datetime(2026, 9, 30, tzinfo=UTC),
                group: items,
            }
        )
    assert error.value.errors()[0]["loc"] == (group,)


@pytest.mark.parametrize("count", [5, 10, 20])
def test_requested_count_preserved_in_execution_contract(count: int) -> None:
    request = SessionCreateRequest(
        request_id="create", search_options=SearchOptions(result_count=count)
    )
    assert request.model_dump()["search_options"] == {"result_count": count}


@pytest.mark.parametrize("count", [4, 21, True, 10.5, "10"])
def test_requested_count_rejects_out_of_bounds_and_coercion(count: object) -> None:
    with pytest.raises(ValidationError) as error:
        SearchOptions.model_validate({"result_count": count})
    assert error.value.errors()[0]["loc"] == ("result_count",)


def test_client_cannot_supply_catalog_identities_or_native_codes() -> None:
    with pytest.raises(ValidationError) as error:
        SessionCreateRequest.model_validate(
            {
                "request_id": "create",
                "preferences": {
                    "location": "Shanghai",
                    "locations": {"included": [{"id": "invented"}]},
                },
            }
        )
    assert error.value.errors()[0]["loc"] == ("preferences", "locations")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (SearchRequest, {}),
        (JobPosting, {"job_id": "job-1"}),
        (WorkflowError, {"code": "error"}),
    ],
)
def test_required_fields_are_enforced(model: type[BaseModel], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)
    assert all(item["type"] == "missing" for item in error.value.errors())


@pytest.mark.parametrize(
    "instance",
    [
        UserProfile(profile_id="p"),
        SearchRequest(target_direction="data analyst"),
        make_job(),
        RecommendationResult(session_id="s", generated_at=datetime(2026, 9, 30, tzinfo=UTC)),
        WorkflowError(code="example", message="example", stage="validation"),
    ],
)
def test_shared_models_reject_extra_fields(instance: BaseModel) -> None:
    payload = instance.model_dump()
    model = type(instance)
    model.model_validate(payload)
    with pytest.raises(ValidationError) as error:
        model.model_validate({**payload, "unexpected": "value"})
    assert [(item["type"], item["loc"]) for item in error.value.errors()] == [
        ("extra_forbidden", ("unexpected",))
    ]
