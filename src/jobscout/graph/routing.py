"""Workflow routing decisions based on validated state."""

from typing import Literal

from jobscout.graph.state import AgentState

ValidationRoute = Literal["clarify", "search", "failed"]
ClarificationRoute = Literal["clarify", "validate", "failed"]
SearchRoute = Literal["process_jobs", "completed", "failed"]
ProcessingRoute = Literal["recommend", "completed", "failed"]
RecommendationRoute = Literal["completed", "failed"]


def route_after_validation(state: AgentState) -> ValidationRoute:
    if state.get("errors"):
        return "failed"

    profile = state.get("profile")
    if profile is None:
        return "clarify"

    if profile.missing_required_fields or profile.conflicts:
        return "clarify"

    return "search"


def route_after_clarification(state: AgentState) -> ClarificationRoute:
    if state.get("errors"):
        return "failed"

    questions = state.get("clarification_questions", [])
    if any(question.required and question.status == "pending" for question in questions):
        return "clarify"

    return "validate"


def route_after_search(state: AgentState) -> SearchRoute:
    if state.get("errors"):
        return "failed"

    if state.get("raw_jobs"):
        return "process_jobs"

    return "completed"


def route_after_processing(state: AgentState) -> ProcessingRoute:
    if state.get("errors"):
        return "failed"

    if state.get("normalized_jobs"):
        return "recommend"

    return "completed"


def route_after_recommendation(state: AgentState) -> RecommendationRoute:
    if state.get("errors"):
        return "failed"

    if state.get("recommendation") is not None:
        return "completed"

    return "failed"
