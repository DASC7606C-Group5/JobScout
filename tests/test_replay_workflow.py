"""Full HTTP workflow with explicitly synthetic replay services."""

import asyncio
import json
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from jobscout.main import create_app
from jobscout.replay.app import create_replay_app
from jobscout.replay.dataset import DEFAULT_DATASET, load_dataset
from jobscout.replay.provider import ReplayProvider
from jobscout.services.llm_service import ToolTurn
from tests.auth_client import AuthenticatedClient as TestClient
from tests.test_web_scaffold import settled

DESCRIPTION = load_dataset().profile_input("data-analyst-internship")["description"]


def test_completed_search_can_reconfirm_unchanged_criteria_on_the_first_attempt() -> None:
    dataset = load_dataset()
    with TestClient(create_replay_app()) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "repeat-create",
                **dataset.profile_input("data-analyst-internship"),
            },
        )
        assert created.status_code == 202, created.json()
        session_id = created.json()["session_id"]
        summary = settled(client, session_id)
        previous_run_id = None
        previous_job_ids: set[str] | None = None
        for attempt in range(2):
            confirmed = client.post(
                f"/api/v1/sessions/{session_id}/resume",
                json={
                    "request_id": f"repeat-confirm-{attempt}",
                    "expected_revision": summary["revision"],
                    "action": "confirm_search",
                },
            )
            assert confirmed.status_code == 202, confirmed.json()
            completed = settled(client, session_id)
            assert completed["session_id"] == session_id
            assert completed["revision"] == summary["revision"] + 1
            assert completed["outcome"] == "completed"
            assert completed["run_id"] is not None
            assert completed["run_id"] != previous_run_id
            jobs = completed["recommendation"]["jobs"]
            assert dataset.jobs[0]["job"]["source_url"] in {
                item["job"]["source_url"] for item in jobs
            }
            job_ids = {item["job"]["job_id"] for item in jobs}
            if previous_job_ids is not None:
                assert job_ids == previous_job_ids
            previous_run_id = completed["run_id"]
            previous_job_ids = job_ids
            if attempt == 0:
                edited = client.post(
                    f"/api/v1/sessions/{session_id}/resume",
                    json={
                        "request_id": "repeat-edit",
                        "expected_revision": completed["revision"],
                        "action": "edit_conditions",
                    },
                )
                assert edited.status_code == 202, edited.json()
                summary = settled(client, session_id)
                assert summary["session_id"] == session_id
                assert summary["revision"] == completed["revision"] + 1
                assert summary["outcome"] == "paused"
                assert summary["current_stage"] == "confirm"
                assert summary["recommendation"] is None
                assert summary["run_id"] is None
                assert summary["search_summary"]["ready"]
                assert not summary["search_summary"]["confirmed"]


def test_replay_apps_use_their_own_profile_and_job_samples(tmp_path: Path) -> None:
    original = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    alternate = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    alternate["profiles"][0]["background"]["skills"] = ["SQL"]
    vacancy = alternate["jobs"][0]
    vacancy["job"]["job_id"] = "alternate-job"
    vacancy["job"]["source_url"] = "https://jobs.example.invalid/alternate-job"
    for requirement in vacancy["requirements"]:
        for reference in requirement["references"]:
            reference["source_url"] = vacancy["job"]["source_url"]
    alternate["jobs"] = [vacancy]
    alternate_path = tmp_path / "alternate.json"
    alternate_path.write_text(json.dumps(alternate), encoding="utf-8")

    for path, dataset in ((alternate_path, alternate), (DEFAULT_DATASET, original)):
        database_url = f"sqlite://{(tmp_path / f'{path.stem}.sqlite3').as_posix()}"
        with TestClient(create_replay_app(dataset_path=path, database_url=database_url)) as client:
            session_id = client.post(
                "/api/v1/sessions",
                json={
                    "request_id": "dataset-create",
                    **dataset["profiles"][0]["input"],
                },
            ).json()["session_id"]
            summary = settled(client, session_id)
            assert summary["outcome"] == "paused", summary
            assert summary["profile"]["skills"] == dataset["profiles"][0]["background"]["skills"]
            response = client.post(
                f"/api/v1/sessions/{session_id}/resume",
                json={
                    "request_id": "dataset-confirm",
                    "expected_revision": summary["revision"],
                    "action": "confirm_search",
                },
            )
            assert response.status_code == 202, response.json()
            result = settled(client, session_id)
            assert result["outcome"] == "completed", result
            source_urls = {item["job"]["source_url"] for item in result["recommendation"]["jobs"]}
            expected_url = dataset["jobs"][0]["job"]["source_url"]
            assert expected_url in source_urls
            if path == alternate_path:
                assert source_urls == {expected_url}
            else:
                assert vacancy["job"]["source_url"] not in source_urls


def test_replay_rejects_missing_or_invalid_datasets(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        create_replay_app(dataset_path=path)
    path.write_text('{"profiles": [], "jobs": [{}]}', encoding="utf-8")
    with pytest.raises(ValidationError) as failure:
        create_replay_app(dataset_path=path)
    assert {tuple(error["loc"]) for error in failure.value.errors()} == {
        ("jobs", 0, "job"),
        ("jobs", 0, "requirements"),
    }


def test_replay_requires_explicit_services_in_the_application_factory() -> None:
    with pytest.raises(ValueError, match="requires injected model and search services"):
        create_app(mode="replay")


@pytest.mark.parametrize("stage", ["search", "review"])
def test_edit_interrupts_active_run_and_requires_reconfirmation(stage: str) -> None:
    class BlockingProvider(ReplayProvider):
        def __init__(self) -> None:
            super().__init__(load_dataset())
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
    with TestClient(create_replay_app(provider=provider)) as client:
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
    from jobscout.replay.provider import ReplayProvider
    from jobscout.services.llm_service import ModelServiceError

    class FailOnce(ReplayProvider):
        def __init__(self) -> None:
            super().__init__(load_dataset())
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
    with TestClient(create_replay_app()) as client:
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
    with TestClient(create_replay_app()) as client:
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
