"""Semantic confirmation routing with model decisions injected at the provider boundary."""

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

from jobscout.schemas.profile import UserProfile
from jobscout.services.conversation_service import AnswerInterpretation, ConversationService
from tests.test_live_graph import FakeProvider, configuration, initial, resume, setup


def test_free_text_confirmation_uses_model_intent_and_preserves_the_user_message() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.intent = "confirm_search"
        graph, _, search, _ = setup(provider)
        original = await graph.ainvoke(initial(), configuration())
        message = "现在开始搜索！"
        result = await graph.ainvoke(resume(message=message), configuration())

        assert result["current_stage"] == "completed"
        assert result["search_summary"].confirmed
        assert result["search_summary"].revision == 2
        assert result["confirmed_profile"].preferences == original["profile"].preferences
        assert any(item.role == "user" and item.text == message for item in result["conversation"])
        assert search.calls
        assert provider.calls.count("AnswerInterpretation") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["answer", "confirm_search"])
@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("先别开始搜索", "defer_search"),
        ("开始搜索是什么意思？", "question"),
    ],
)
def test_deferral_or_question_never_starts_search(action: str, message: str, intent: str) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.intent = intent
        graph, _, search, _ = setup(provider)
        original = await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action=action, message=message), configuration())

        assert state["current_stage"] == "confirm"
        assert state["outcome"] == "paused"
        assert not state["search_summary"].confirmed
        assert state["confirmed_profile"] is None
        assert state["profile"] == original["profile"]
        assert not search.calls

    asyncio.run(scenario())


def test_uncertain_text_does_not_confirm_even_when_it_mentions_search() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        graph, _, search, _ = setup(provider)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(
            resume(message="也许之后可以开始搜索，我还没想好"), configuration()
        )
        assert state["current_stage"] == "confirm"
        assert state["confirmed_profile"] is None
        assert not search.calls

    asyncio.run(scenario())


def test_correction_and_confirmation_require_review_of_the_updated_conditions() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.intent = "confirm_search"
        provider.changes = [{"field": "preferences.location", "value": "Shanghai"}]
        graph, _, search, _ = setup(provider)
        await graph.ainvoke(initial(), configuration())
        edited = await graph.ainvoke(resume(message="改成上海，然后开始搜索"), configuration())

        assert edited["current_stage"] == "confirm"
        assert not edited["search_summary"].confirmed
        assert edited["search_summary"].revision == 2
        assert edited["search_summary"].profile.preferences.location == "Shanghai"
        assert edited["confirmed_profile"] is None
        assert not search.calls

        provider.changes = []
        confirmed = await graph.ainvoke(resume(2, message="按新条件开始吧"), configuration())
        assert confirmed["search_summary"].confirmed
        assert search.calls
        assert all(
            request.location_ref is not None and request.location_ref.id == "cn:538"
            for requests in search.calls
            for request in requests
        )

    asyncio.run(scenario())


def test_model_confirmation_cannot_bypass_missing_conditions() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.intent = "confirm_search"
        graph, _, search, _ = setup(provider)
        await graph.ainvoke(initial(target_directions=[]), configuration())
        state = await graph.ainvoke(resume(message="直接开始搜索吧"), configuration())
        assert state["outcome"] == "paused"
        assert state["confirmed_profile"] is None
        assert "target_directions" in state["profile"].missing_required_fields
        assert not search.calls

    asyncio.run(scenario())


def test_edit_action_cannot_start_search_from_model_intent() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.intent = "confirm_search"
        graph, _, search, _ = setup(provider)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(
            resume(action="edit_conditions", message="开始搜索"), configuration()
        )
        assert state["outcome"] == "paused"
        assert state["confirmed_profile"] is None
        assert not search.calls

    asyncio.run(scenario())


def test_failed_interpretation_does_not_fall_back_to_confirmation_keywords() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.fail = "AnswerInterpretation"
        graph, _, search, _ = setup(provider)
        original = await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(message="确认搜索"), configuration())
        assert state["outcome"] == "failed"
        assert state["retryable"]
        assert any(error.code == "model_output" for error in state["errors"])
        assert state["profile"] == original["profile"]
        assert state["confirmed_profile"] is None
        assert not search.calls

    asyncio.run(scenario())


def test_interpretation_supplies_confirmation_context_and_retains_both_intent_and_edits() -> None:
    class Provider(FakeProvider):
        payload: dict[str, Any]

        async def structured[T: BaseModel](
            self,
            schema: type[T],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> T:
            if schema is AnswerInterpretation:
                self.payload = json.loads(messages[-1]["content"])
            return await super().structured(schema, messages, deadline=deadline)

    provider = Provider()
    provider.intent = "confirm_search"
    provider.changes = [{"field": "preferences.location", "value": "上海 / Shanghai"}]
    profile = UserProfile(profile_id="profile-1", skills=["Python"])
    message = "改成上海 / Shanghai，然后开始搜索！"
    interpretation = asyncio.run(
        ConversationService(provider).interpret(profile, message, confirmation_ready=True)
    )

    assert provider.payload["message"] == message
    assert provider.payload["profile"] == profile.model_dump(mode="json")
    assert provider.payload["confirmation_ready"] is True
    assert interpretation.intent == "confirm_search"
    assert [(change.field, change.value) for change in interpretation.changes] == [
        ("preferences.location", "上海 / Shanghai")
    ]
