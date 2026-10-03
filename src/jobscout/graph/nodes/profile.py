from collections.abc import Mapping
from typing import TypedDict

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.search import SearchRequest
from jobscout.services.profile_service import (
    InputFormatError,
    build_profile,
    parse_profile_input,
    required_missing_fields,
)


class ProfileNodeUpdate(TypedDict, total=False):
    profile: UserProfile
    search_requests: list[SearchRequest]
    warnings: list[str]
    errors: list[WorkflowError]
    current_stage: str


def extract_profile_node(state: AgentState) -> ProfileNodeUpdate:
    if state.get("profile") is not None:
        return {"current_stage": "profile"}

    raw_input: object = state.get("input_data")
    if raw_input is None:
        input_data: Mapping[str, object] = {}
    elif isinstance(raw_input, Mapping):
        input_data = raw_input
    else:
        return {
            "errors": [
                WorkflowError(
                    code="invalid_input", message="input_data must be an object.", stage="profile"
                )
            ],
            "current_stage": "profile",
        }
    try:
        parsed = parse_profile_input(input_data)
    except InputFormatError as error:
        return {
            "errors": [WorkflowError(code="invalid_input", message=str(error), stage="profile")],
            "current_stage": "profile",
        }

    profile = build_profile(
        state["session_id"],
        description=parsed.description,
        resume=parsed.resume,
        target_directions=parsed.target_directions,
        preferences=parsed.preferences,
    )
    update: ProfileNodeUpdate = {"profile": profile, "current_stage": "profile"}
    if not profile.source.resume and not profile.source.description:
        update["warnings"] = ["No resume or personal description was provided."]
    return update


def validate_profile_node(state: AgentState) -> ProfileNodeUpdate:
    profile = state.get("profile")
    if profile is None:
        return {
            "warnings": ["No profile is available for validation."],
            "current_stage": "validate",
        }

    validated = profile.model_copy(
        update={"missing_required_fields": required_missing_fields(profile)}
    )
    update: ProfileNodeUpdate = {"profile": validated, "current_stage": "validate"}
    if not validated.missing_required_fields and not validated.conflicts:
        update["search_requests"] = _build_search_requests(validated)
    return update


def _build_search_requests(profile: UserProfile) -> list[SearchRequest]:
    preferences = profile.preferences
    employment_type = preferences.employment_type
    if employment_type is None:
        return []
    return [
        SearchRequest(
            target_direction=direction,
            keywords=list(profile.skills),
            location=preferences.location,
            location_unrestricted=preferences.location_unrestricted,
            employment_type=employment_type,
            salary_range=preferences.salary_range,
            work_mode=preferences.work_mode,
        )
        for direction in profile.target_directions
    ]
