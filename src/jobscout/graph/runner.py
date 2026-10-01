"""Workflow execution entry points for the graph layer."""

from typing import Any, Literal, TypedDict, cast

from langgraph.types import Command

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError

WorkflowOutcome = Literal["paused", "completed", "failed"]


class WorkflowResult(TypedDict):
    """Outcome and state returned by one graph execution."""

    outcome: WorkflowOutcome
    state: AgentState


def run_workflow(
    graph: Any,
    session_id: str,
    input_data: dict[str, object] | None = None,
    answers: dict[str, object] | None = None,
) -> WorkflowResult:
    """Run or resume a workflow using session_id as the graph thread id."""
    config: dict[str, dict[str, str]] = {"configurable": {"thread_id": session_id}}
    try:
        if answers is None:
            initial_state: AgentState = {"session_id": session_id}
            if input_data is not None:
                initial_state["input_data"] = input_data
            state = cast(AgentState, graph.invoke(initial_state, config))
        else:
            state = cast(
                AgentState,
                graph.invoke(Command(resume={"answers": answers}), config),
            )

        return {
            "outcome": _classify_outcome(graph, config, state),
            "state": state,
        }
    except Exception as error:
        state = _state_from_checkpoint(graph, config, session_id)
        state["current_stage"] = "failed"
        errors = list(state.get("errors", []))
        errors.append(
            WorkflowError(
                code="workflow_execution_error",
                message=str(error),
                stage="workflow",
            )
        )
        state["errors"] = errors
        return {"outcome": "failed", "state": state}


def _classify_outcome(graph: Any, config: Any, state: AgentState) -> WorkflowOutcome:
    current_stage = state.get("current_stage")
    if current_stage == "failed":
        return "failed"
    if current_stage == "completed":
        return "completed"

    snapshot = graph.get_state(config)
    if current_stage == "clarify" and snapshot.next == ("clarify",):
        return "paused"
    raise ValueError("Workflow stopped without a recognized terminal outcome.")


def _state_from_checkpoint(graph: Any, config: Any, session_id: str) -> AgentState:
    try:
        snapshot = graph.get_state(config)
        values = snapshot.values
        if isinstance(values, dict) and "session_id" in values:
            return cast(AgentState, dict(values))
    except Exception:
        pass
    return {"session_id": session_id}
