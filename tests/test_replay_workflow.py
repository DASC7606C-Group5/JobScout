"""Full HTTP workflow with explicitly synthetic replay services."""

import asyncio
import json
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from jobscout.main import create_app
from jobscout.services.llm_service import ToolTurn
from jobscout.services.replay_service import ReplayProvider
from tests.test_web_scaffold import settled

DESCRIPTION = (
    "Education\nBachelor Computer Science\nSkills\nPython, SQL, Excel\n"
    "Projects\nPython SQL reporting dashboard"
)


@pytest.mark.parametrize("stage", ["search", "review"])
def test_edit_interrupts_active_run_and_requires_reconfirmation(stage: str) -> None:
    class BlockingProvider(ReplayProvider):
        def __init__(self) -> None:
            self.started = Event()
            self.cancelled = Event()

        async def block_once(self) -> None:
            if self.started.is_set():
                return
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

        async def tool_turn(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            *,
            deadline: float | None = None,
        ) -> ToolTurn:
            if stage == "search":
                await self.block_once()
            return await super().tool_turn(messages, tools, deadline=deadline)

        async def structured[T: BaseModel](
            self,
            schema: type[T],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> T:
            if (
                stage == "review"
                and json.loads(messages[-1]["content"]).get("task") == "jd_analysis"
            ):
                await self.block_once()
            return await super().structured(schema, messages, deadline=deadline)

    provider = BlockingProvider()
    with TestClient(create_app(mode="replay", provider=provider)) as client:
        session_id = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "active-create",
                "description": DESCRIPTION,
                "target_directions": ["Data Analyst"],
                "preferences": {"location": "Hong Kong", "employment_type": "internship"},
            },
        ).json()["session_id"]
        summary = settled(client, session_id)
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "active-confirm",
                "expected_revision": summary["revision"],
                "action": "confirm_search",
            },
        )
        assert confirmed.status_code == 202, confirmed.json()
        assert provider.started.wait(timeout=5)
        running = client.get(f"/api/v1/sessions/{session_id}").json()
        assert running["outcome"] == "running"
        assert running["run_id"] is not None
        stale = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "stale-active-edit",
                "expected_revision": running["revision"] - 1,
                "action": "edit_conditions",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "search_changed"
        assert not provider.cancelled.is_set()
        payload = {
            "request_id": "active-edit",
            "expected_revision": running["revision"],
            "action": "edit_conditions",
        }
        edited = client.post(f"/api/v1/sessions/{session_id}/resume", json=payload)
        assert edited.status_code == 202, edited.json()
        assert provider.cancelled.wait(timeout=5)
        new_summary = settled(client, session_id)
        assert new_summary["session_id"] == session_id
        assert new_summary["revision"] == running["revision"] + 1
        assert new_summary["outcome"] == "paused"
        assert new_summary["current_stage"] == "confirm"
        assert new_summary["search_summary"]["confirmed"] is False
        assert new_summary["profile"] == running["profile"]
        assert new_summary["recommendation"] is None
        assert new_summary["run_id"] is None
        assert new_summary["progress"]["sequence"] == 0
        repeat = client.post(f"/api/v1/sessions/{session_id}/resume", json=payload)
        assert repeat.status_code == 202
        assert repeat.json()["revision"] == new_summary["revision"]
        reconfirmed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "active-reconfirm",
                "expected_revision": new_summary["revision"],
                "action": "confirm_search",
            },
        )
        assert reconfirmed.status_code == 202, reconfirmed.json()
        assert settled(client, session_id)["outcome"] == "completed"


def test_failed_profile_retry_uses_clean_checkpoint_and_retains_materials() -> None:
    from jobscout.services.llm_service import ModelServiceError
    from jobscout.services.replay_service import ReplayProvider

    class FailOnce(ReplayProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def structured[T: BaseModel](
            self,
            schema: type[T],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> T:
            self.calls += 1
            if self.calls == 1:
                raise ModelServiceError("model_output")
            return await super().structured(schema, messages, deadline=deadline)

    provider = FailOnce()
    application = create_app(provider=provider)
    with TestClient(application) as client:
        session_id = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "failing-profile",
                "description": DESCRIPTION,
                "target_directions": ["Data Analyst"],
                "preferences": {"location": "Hong Kong", "employment_type": "internship"},
            },
        ).json()["session_id"]
        failed = settled(client, session_id)
        assert failed["outcome"] == "failed"
        retried = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "retry-profile",
                "expected_revision": failed["revision"],
                "action": "retry",
            },
        )
        assert retried.status_code == 202
        summary = settled(client, session_id)
        assert summary["outcome"] == "paused", summary
        assert summary["errors"] == []
        assert set(summary["profile"]["skills"]) == {"Python", "SQL", "Excel"}
        record: Any = application.state.sessions.sessions[session_id]
        assert len(record.thread_ids) == 2
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204


def test_dynamic_replay_choices_preserve_equivalent_location_matching() -> None:
    with TestClient(create_app(mode="replay")) as client:
        session_id = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "dynamic-create",
                "description": DESCRIPTION,
            },
        ).json()["session_id"]
        questions = settled(client, session_id)
        values: dict[str, str | list[str]] = {
            "target_directions": ["Data Analyst"],
            "preferences.location": "Hong Kong",
            "preferences.employment_type": "internship",
        }
        answers = [
            {"question_id": question["question_id"], "value": values[question["field"]]}
            for question in questions["clarification_questions"]
        ]
        response = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "dynamic-answer",
                "expected_revision": questions["revision"],
                "answers": answers,
            },
        )
        assert response.status_code == 202, response.json()
        summary = settled(client, session_id)
        assert summary["current_stage"] == "confirm", summary
        response = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "dynamic-confirm",
                "expected_revision": summary["revision"],
                "action": "confirm_search",
            },
        )
        assert response.status_code == 202, response.json()
        results = settled(client, session_id)
        assert results["outcome"] == "completed", results
        assert results["recommendation"]["jobs"], results


def test_replay_confirm_search_edit_and_reconfirm() -> None:
    with TestClient(create_app(mode="replay")) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "replay-create",
                "description": DESCRIPTION,
                "target_directions": ["Data Analyst"],
                "preferences": {"location": "Hong Kong", "employment_type": "internship"},
            },
        )
        assert created.status_code == 202
        session_id = created.json()["session_id"]
        summary = settled(client, session_id)
        assert summary["outcome"] == "paused", summary
        assert summary["current_stage"] == "confirm", summary
        assert summary["search_summary"]["revision"] == summary["revision"]
        assert summary["recommendation"] is None
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "replay-confirm",
                "expected_revision": summary["revision"],
                "action": "confirm_search",
            },
        )
        assert confirmed.status_code == 202, confirmed.json()
        results = settled(client, session_id)
        assert results["outcome"] == "completed", results
        assert results["mode"] == "replay"
        assert results["recommendation"] is not None
        assert len(results["recommendation"]["jobs"]) <= 5
        edited = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "replay-edit",
                "expected_revision": results["revision"],
                "action": "edit_conditions",
                "profile_updates": {"preferences.location": "深圳"},
            },
        )
        assert edited.status_code == 202, edited.json()
        assert edited.json()["recommendation"] is None
        new_summary = settled(client, session_id)
        assert new_summary["outcome"] == "paused", new_summary
        assert new_summary["current_stage"] == "confirm"
        assert new_summary["profile"]["preferences"]["location"] == "深圳"
        assert new_summary["recommendation"] is None
        assert new_summary["search_summary"]["revision"] == new_summary["revision"]
        confirmed_again = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "replay-confirm-new",
                "expected_revision": new_summary["revision"],
                "action": "confirm_search",
            },
        )
        assert confirmed_again.status_code == 202, confirmed_again.json()
        assert settled(client, session_id)["outcome"] == "completed"
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
