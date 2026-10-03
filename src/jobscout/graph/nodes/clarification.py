from typing import TypedDict

from langgraph.types import interrupt

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.search import ClarificationMessage
from jobscout.services.profile_service import apply_answers, build_clarification_questions


class ClarificationNodeUpdate(TypedDict, total=False):
    profile: UserProfile
    clarification_questions: list[ClarificationMessage]
    warnings: list[str]
    errors: list[WorkflowError]
    current_stage: str


def clarification_node(state: AgentState) -> ClarificationNodeUpdate:
    profile = state.get("profile")
    existing = list(state.get("clarification_questions") or [])

    if not existing:
        return {
            "clarification_questions": build_clarification_questions(profile),
            "current_stage": "clarify",
        }

    resumed = interrupt(
        {
            "questions": [question.model_dump(mode="json") for question in existing],
            "message": "Answer the pending clarification questions to continue.",
        }
    )
    answers: object = resumed.get("answers", {}) if isinstance(resumed, dict) else {}
    if profile is None:
        return {
            "errors": [
                WorkflowError(
                    code="invalid_input",
                    message="No profile is available to update.",
                    stage="clarify",
                )
            ],
            "current_stage": "clarify",
        }
    if not isinstance(answers, dict):
        return {"current_stage": "clarify"}

    updated_profile, updated_questions = apply_answers(profile, existing, answers)
    return {
        "profile": updated_profile,
        "clarification_questions": updated_questions,
        "current_stage": "clarify",
    }
