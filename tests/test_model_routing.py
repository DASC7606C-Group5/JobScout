"""Exercise model roles through the production graph with synthetic HTTP responses."""

import asyncio
import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from jobscout.config import Settings
from jobscout.graph.live import build_live_graph
from jobscout.services.condition_service import PreferenceMeaning
from jobscout.services.conversation_service import (
    AnswerInterpretation,
    ConversationService,
    ProfileExtraction,
    QuestionGeneration,
)
from jobscout.services.job_assessment_service import (
    JDAnalysisBatch,
    JobAssessmentService,
    MatchingBatch,
)
from jobscout.services.llm_service import get_llm_provider
from jobscout.services.prompts import STRUCTURED_OUTPUT_PROMPT
from tests.test_job_assessment_service import PROFILE_DOCUMENTS, ReplayProvider, job, profile
from tests.test_live_graph import FakeProvider, FakeSearch, configuration, initial, raw, resume


def settings() -> Settings:
    return Settings.model_construct(
        llm_semantic_model="synthetic-semantic",
        llm_semantic_base_url="https://semantic.example.invalid/v1",
        llm_semantic_api_key="synthetic-semantic-key",
        llm_decision_model="synthetic-decision",
        llm_decision_base_url="https://decision.example.invalid/v2",
        llm_decision_api_key="synthetic-decision-key",
    )


def install_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str, str]]:
    conversation = FakeProvider()
    assessment = ReplayProvider()
    schemas: dict[str, type[BaseModel]] = {
        schema.__name__: schema
        for schema in (
            ProfileExtraction,
            PreferenceMeaning,
            QuestionGeneration,
            AnswerInterpretation,
            JDAnalysisBatch,
            MatchingBatch,
        )
    }
    requests: list[tuple[str, str, str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "tools" in body:
            schema_name = "tool_turn"
            turn = await conversation.tool_turn(body["messages"], body["tools"])
            message = turn.assistant_message()
            if body.get("thinking") == {"type": "enabled"}:
                message["reasoning_content"] = "synthetic-private-tool-reasoning"
                for previous in body["messages"]:
                    if previous["role"] == "assistant" and previous.get("tool_calls"):
                        assert previous["reasoning_content"] == "synthetic-private-tool-reasoning"
            finish = "tool_calls"
        else:
            schema_name = json.loads(
                body["messages"][0]["content"].removeprefix(STRUCTURED_OUTPUT_PROMPT)
            )["title"]
            schema = schemas[schema_name]
            delegate = assessment if schema in (JDAnalysisBatch, MatchingBatch) else conversation
            response = await delegate.structured(schema, body["messages"][1:])
            message = {"role": "assistant", "content": response.model_dump_json()}
            finish = "stop"
        requests.append(
            (schema_name, str(request.url), request.headers["authorization"], body["model"])
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    client_factory = httpx.AsyncClient
    monkeypatch.setattr(
        "jobscout.services.llm_service._new_http_client",
        lambda: client_factory(transport=httpx.MockTransport(handler)),
    )
    return requests


@pytest.mark.parametrize("thinking", [False, True])
def test_graph_routes_conversation_and_jd_to_semantic_search_and_matching_to_decision(
    monkeypatch: pytest.MonkeyPatch,
    thinking: bool,
) -> None:
    requests = install_transport(monkeypatch)
    active = settings()
    active.llm_decision_thinking = thinking
    provider = get_llm_provider(active)
    directory = ReplayProvider().location_catalog
    monkeypatch.setattr(provider, "location_catalog", directory, raising=False)
    monkeypatch.setattr(
        "jobscout.services.recommendation_service.get_location_catalog", lambda: directory
    )

    async def scenario() -> None:
        from jobscout.services.job_retrieval.models import SearchResult

        candidates = [raw(index) for index in range(5)]
        for candidate in candidates:
            candidate.description = "Python required. Bachelor degree required."
        checkpointer = InMemorySaver()
        graph = build_live_graph(
            checkpointer, provider, FakeSearch([SearchResult(raw_jobs=candidates)])
        )
        state = await graph.ainvoke(initial(), configuration())
        assert state["current_stage"] == "confirm"
        assert state["profile"] is not None
        interpreted = await ConversationService(provider).interpret(
            state["profile"], "Keep my current preferences."
        )
        assert interpreted.intent == "answer"
        before_search = provider.usage.requests
        completed = await graph.ainvoke(
            resume(state["revision"], action="confirm_search"), configuration()
        )
        assert completed["current_stage"] == "completed"
        assert {row.job.source_url for row in completed["recommendation"].jobs} == {
            candidate.source_url for candidate in candidates
        }
        search_requests = provider.usage.requests - before_search
        assert completed["model_usage"]["requests"] == search_requests
        assert completed["model_usage"]["total_tokens"] == search_requests * 5
        stored = repr((checkpointer.storage, checkpointer.writes, checkpointer.blobs))
        for secret in (
            "synthetic-semantic-key",
            "synthetic-decision-key",
            "synthetic-private-tool-reasoning",
        ):
            assert secret not in stored
            assert secret not in repr(completed)

    asyncio.run(scenario())
    assert {name for name, *_ in requests} == {
        "ProfileExtraction",
        "PreferenceMeaning",
        "QuestionGeneration",
        "AnswerInterpretation",
        "JDAnalysisBatch",
        "MatchingBatch",
        "tool_turn",
    }
    for schema, url, authorization, model in requests:
        role = "decision" if schema in {"MatchingBatch", "tool_turn"} else "semantic"
        version = "v2" if role == "decision" else "v1"
        assert url == f"https://{role}.example.invalid/{version}/chat/completions"
        assert authorization == f"Bearer synthetic-{role}-key"
        assert model == f"synthetic-{role}"


def test_jd_cache_tracks_semantic_model_and_endpoint_but_recomputes_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_transport(monkeypatch)
    active_settings = settings()

    async def scenario() -> None:
        provider = get_llm_provider(active_settings)
        service = JobAssessmentService(provider)
        await service.begin_search("first")
        candidate = job("a")
        first = await service.assess(profile(), [candidate], PROFILE_DOCUMENTS, "s")
        assert first.jobs[0].matching_reasons[0].level == "strong"
        snapshot = service.export_cache()

        active_settings.llm_decision_model = "synthetic-new-decision"
        restored = JobAssessmentService(get_llm_provider(active_settings))
        restored.import_cache(snapshot, "s")
        await restored.begin_search("second")
        user = profile()
        user.skills = []
        second = await restored.assess(user, [candidate], PROFILE_DOCUMENTS, "s")
        assert second.jobs[0].matching_reasons[0].level == "not_documented"
        assert [name for name, *_ in requests] == [
            "JDAnalysisBatch",
            "MatchingBatch",
            "MatchingBatch",
        ]
        assert requests[-1][-1] == "synthetic-new-decision"

        active_settings.llm_semantic_base_url = "https://other-semantic.example.invalid/v3"
        changed = JobAssessmentService(get_llm_provider(active_settings))
        changed.import_cache(snapshot, "s")
        await changed.begin_search("third")
        await changed.assess(user, [candidate], PROFILE_DOCUMENTS, "s")
        assert [name for name, *_ in requests[-2:]] == ["JDAnalysisBatch", "MatchingBatch"]
        assert requests[-2][1] == "https://other-semantic.example.invalid/v3/chat/completions"

    asyncio.run(scenario())
