"""Graph node entry points for profile extraction, validation, and updates."""

from collections.abc import Mapping
from typing import TypedDict

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.profile import UserProfile
from jobscout.services.profile_service import (
    InputFormatError,
    build_profile,
    parse_profile_input,
    required_missing_fields,
)


class ProfileNodeUpdate(TypedDict, total=False):
    """Partial ``AgentState`` update returned by the profile nodes."""

    profile: UserProfile
    warnings: list[str]
    errors: list[WorkflowError]
    current_stage: str


def extract_profile_node(state: AgentState) -> ProfileNodeUpdate:
    """Extract a ``UserProfile`` from the standardized session input.

    Re-running the node with an existing profile is a no-op, so graph retries and
    interrupt resumes never overwrite profile data that is already confirmed.
    A non-mapping ``input_data`` value is reported as ``invalid_input`` instead of
    raising, so a malformed API payload fails the session instead of the process.

    Args:
        state: Current workflow state.

    Returns:
        A partial state update holding the profile, stage, and any warning/error.
    """
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
    """Recompute required-field gaps after clarification answers are written back.

    Args:
        state: Current workflow state.

    Returns:
        A partial state update with the revalidated profile and stage.
    """
    profile = state.get("profile")
    if profile is None:
        return {
            "warnings": ["No profile is available for validation."],
            "current_stage": "validate",
        }

    validated = profile.model_copy(
        update={"missing_required_fields": required_missing_fields(profile)}
    )
    return {"profile": validated, "current_stage": "validate"}
