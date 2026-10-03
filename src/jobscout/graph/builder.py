from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from jobscout.graph.nodes.clarification import clarification_node
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
from jobscout.graph.nodes.process_jobs import process_jobs_node
from jobscout.graph.nodes.profile import extract_profile_node, validate_profile_node
from jobscout.graph.nodes.recommend import recommend_node
from jobscout.graph.nodes.search import search_node
from jobscout.graph.routing import (
    route_after_clarification,
    route_after_processing,
    route_after_recommendation,
    route_after_search,
    route_after_validation,
)
from jobscout.graph.state import AgentState


def _compile_graph(
    profile: Any,
    validate: Any,
    clarify: Any,
    search: Any,
    process_jobs: Any,
    recommend: Any,
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    graph = StateGraph(AgentState)
    graph.add_node("profile", cast(Any, profile))
    graph.add_node("validate", cast(Any, validate))
    graph.add_node("clarify", cast(Any, clarify))
    graph.add_node("search", cast(Any, search))
    graph.add_node("process_jobs", cast(Any, process_jobs))
    graph.add_node("recommend", cast(Any, recommend))
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


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    return _compile_graph(
        extract_profile_node,
        validate_profile_node,
        clarification_node,
        search_node,
        process_jobs_node,
        recommend_node,
        checkpointer,
    )


def build_mock_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    return _compile_graph(
        mock_profile_node,
        mock_validation_node,
        mock_clarification_node,
        mock_search_node,
        mock_processing_node,
        mock_recommendation_node,
        checkpointer,
    )
