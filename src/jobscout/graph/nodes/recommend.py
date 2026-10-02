"""Thin recommendation node; workflow wiring belongs to group 3."""

from typing import TypedDict

from jobscout.graph.state import AgentState, WorkflowStage
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.services.recommendation_service import RecommendationError, recommend_jobs


class RecommendationNodeUpdate(TypedDict, total=False):
    recommendation: RecommendationResult | None
    current_stage: WorkflowStage
    errors: list[WorkflowError]
    warnings: list[str]


def recommend_node(state: AgentState) -> RecommendationNodeUpdate:
    """Read normalized data and return a partial update, including error data."""
    profile = state.get("profile")
    if profile is None:
        return {
            "recommendation": None,
            "current_stage": "failed",
            "errors": [
                WorkflowError(
                    code="recommendation_missing_profile",
                    message="无法生成推荐：缺少 UserProfile。",
                    stage="recommend",
                )
            ],
        }
    try:
        result = recommend_jobs(
            profile,
            state.get("normalized_jobs", []),
            session_id=state["session_id"],
            warnings=state.get("warnings", []),
        )
    except RecommendationError as exc:
        return {"recommendation": None, "current_stage": "failed", "errors": [exc.error]}
    # AgentState appends warnings via a reducer: emit only new recommendation warnings.
    existing_warnings = set(state.get("warnings", []))
    return {
        "recommendation": result,
        "current_stage": "recommend",
        "warnings": [warning for warning in result.warnings if warning not in existing_warnings],
    }
