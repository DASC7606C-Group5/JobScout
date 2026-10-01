"""StateGraph construction and compilation."""

from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from jobscout.graph.nodes.mock import (
    mock_clarification_node,
    mock_completed_node,
    mock_failed_node,
    mock_processing_node,
    mock_profile_node,
    mock_recommendation_node,
    mock_search_node,
    mock_validation_node,
)
from jobscout.graph.routing import (
    route_after_clarification,
    route_after_processing,
    route_after_recommendation,
    route_after_search,
    route_after_validation,
)
from jobscout.graph.state import AgentState


def build_mock_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Build and compile the branch-capable fixed-data workflow."""
    graph = StateGraph(AgentState)
    graph.add_node("profile", cast(Any, mock_profile_node))
    graph.add_node("validate", cast(Any, mock_validation_node))
    graph.add_node("clarify", cast(Any, mock_clarification_node))
    graph.add_node("search", cast(Any, mock_search_node))
    graph.add_node("process_jobs", cast(Any, mock_processing_node))
    graph.add_node("recommend", cast(Any, mock_recommendation_node))
    graph.add_node("completed", cast(Any, mock_completed_node))
    graph.add_node("failed", cast(Any, mock_failed_node))

    graph.add_edge(START, "profile")
    graph.add_edge("profile", "validate")
    graph.add_conditional_edges(
        "validate",
        cast(Any, route_after_validation),
        {"clarify": "clarify", "search": "search", "failed": "failed"},
    )
    graph.add_conditional_edges(
        "clarify",
        cast(Any, route_after_clarification),
        {"clarify": "clarify", "validate": "validate", "failed": "failed"},
    )
    graph.add_conditional_edges(
        "search",
        cast(Any, route_after_search),
        {"process_jobs": "process_jobs", "completed": "completed", "failed": "failed"},
    )
    graph.add_conditional_edges(
        "process_jobs",
        cast(Any, route_after_processing),
        {"recommend": "recommend", "completed": "completed", "failed": "failed"},
    )
    graph.add_conditional_edges(
        "recommend",
        cast(Any, route_after_recommendation),
        {"completed": "completed", "failed": "failed"},
    )
    graph.add_edge("completed", END)
    graph.add_edge("failed", END)

    return graph.compile(checkpointer=checkpointer)
