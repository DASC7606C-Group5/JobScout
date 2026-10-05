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
    profile = state.get("profile")
    if profile is None:
        return {
            "recommendation": None,
            "current_stage": "failed",
            "errors": [
                WorkflowError(
                    code="recommendation_missing_profile",
                    message="Could not generate recommendations: UserProfile is missing.",
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
    existing_warnings = set(state.get("warnings", []))
    return {
        "recommendation": result,
        "current_stage": "recommend",
        "warnings": [warning for warning in result.warnings if warning not in existing_warnings],
    }
