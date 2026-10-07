"""Career APIs use temporary SQLite files and supplied job snapshots."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from jobscout.graph.live import build_live_graph
from jobscout.main import create_app
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.services.career_service import refresh_task_background
from jobscout.services.conversation_service import missing_fields
from jobscout.services.llm_service import LLMProvider
from jobscout.services.session_service import _Session
from tests.test_conditions_and_locations import MeaningProvider
from tests.test_session_operations import ControlledGraph

NOW = datetime(2026, 10, 7, tzinfo=UTC)
JOB_ID = "source:jobs/42"


def seed(client: TestClient, session_id: str, job_id: str = JOB_ID) -> None:
    async def write() -> None:
        sessions = cast(Any, client.app).state.sessions
        item = RecommendationItem(
            job=JobPosting(
                job_id=job_id,
                source="test",
                source_url="https://example.com/jobs/42",
                title="Engineer",
                company="Example",
                location="Hong Kong",
                target_direction="Engineer",
                fetched_at=NOW,
            )
        )
        profile = UserProfile(
            profile_id=session_id,
            education=["Degree"],
            skills=["Python"],
            target_directions=["Engineer"],
            preferences=ProfilePreferences(location="Hong Kong", employment_type="full-time"),
        )
        record = _Session(
            session_id,
            {
                "session_id": session_id,
                "current_stage": "completed",
                "profile": profile,
                "recommendation": RecommendationResult(
                    session_id=session_id, generated_at=NOW, jobs=[item]
                ),
                "input_data": {"description": "Original supplied background"},
                "profile_documents": [
                    SourceDocument(
                        document_id=f"profile:{session_id}:description",
                        source="user",
                        source_url="",
                        text="Original supplied background",
                        fetched_at=NOW,
                    )
                ],
            },
            outcome="completed",
            thread_id=session_id,
            thread_ids=[session_id],
        )
        sessions.sessions[session_id] = record
        await sessions._persist(record)

    cast(Any, client.portal).call(write)


def profile_payload(revision: int = 0) -> dict[str, Any]:
    return {
        "expected_revision": revision,
        "description": "  Original description\n",
        "resume": {"name": "cv.txt", "text": "Resume exact text\n"},
        "background": {
            "education": ["Degree"],
            "skills": ["SQL"],
            "internships": [],
            "projects": ["Analytics"],
        },
        "documents": [
            {
                "document_id": "evidence:project",
                "source": "user",
                "source_url": "",
                "text": "Project evidence",
                "fetched_at": NOW.isoformat(),
                "is_excerpt": False,
            }
        ],
    }


def test_profile_restart_conflict_and_draft_does_not_publish(tmp_path: Path) -> None:
    database = f"sqlite://{(tmp_path / 'profile.sqlite3').as_posix()}"
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        assert client.get("/api/v1/profile").json()["revision"] == 0
        draft = client.put(
            "/api/v1/workspace/draft",
            json={
                "request_id": "raw-draft",
                "expected_revision": 0,
                "data": {
                    "description": "Unpublished edits",
                    "resume": None,
                    "directions": "Engineer",
                    "preferences": {
                        "location": None,
                        "location_unrestricted": True,
                        "employment_type": None,
                        "employment_type_unrestricted": True,
                        "salary_range": None,
                        "work_mode": None,
                        "industry": None,
                    },
                },
            },
        )
        assert draft.status_code == 200
        assert client.get("/api/v1/profile").json()["revision"] == 0
        response = client.put("/api/v1/profile", json=profile_payload())
        assert response.status_code == 200
        assert response.json()["revision"] == 1
        assert client.put("/api/v1/profile", json=profile_payload()).status_code == 409
    for _ in range(2):
        with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
            current = client.get("/api/v1/profile").json()
            assert current["description"] == "  Original description\n"
            assert current["resume"] == profile_payload()["resume"]
            assert current["background"]["skills"] == ["SQL"]
            assert current["documents"][0]["document_id"] == "evidence:project"
            assert (
                client.get("/api/v1/workspace/draft").json()["data"]["description"]
                == "Unpublished edits"
            )


def test_feedback_ownership_undo_and_global_progress_survive_delete(tmp_path: Path) -> None:
    database = f"sqlite://{(tmp_path / 'tracking.sqlite3').as_posix()}"
    path = f"/api/v1/applications/{quote(JOB_ID, safe='')}"
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        seed(client, "task-a")
        seed(client, "task-b")
        seed(client, "other", "source:other")
        feedback = f"/api/v1/sessions/task-a/feedback/{quote(JOB_ID, safe='')}"
        response = client.put(
            feedback, json={"interest": "not_interested", "reason": "Commute", "scope": "task"}
        )
        assert response.status_code == 200
        assert response.json()["job_id"] == JOB_ID
        assert client.get("/api/v1/sessions/task-b/feedback").json() == []
        assert (
            client.put(
                f"/api/v1/sessions/other/feedback/{quote(JOB_ID, safe='')}",
                json={"interest": "interested"},
            ).status_code
            == 404
        )
        assert (
            client.put(
                path, json={"session_id": "task-a", "stage": "applied", "note": "Submitted"}
            ).status_code
            == 200
        )
        response = client.put(
            path, json={"session_id": "task-b", "stage": "interview", "note": "Tuesday"}
        )
        assert [entry["stage"] for entry in response.json()["history"]] == ["applied", "interview"]
        assert client.get(feedback).json()["interest"] == "not_interested"
        assert (
            client.put(feedback, json={"interest": "neutral", "reason": "", "scope": "job"}).json()[
                "interest"
            ]
            == "neutral"
        )
        assert client.put(path, json={"stage": "closed"}).status_code == 200
        assert client.put(path, json={"stage": "applied", "note": "Reopened"}).status_code == 200
        assert (
            client.put("/api/v1/applications/invented", json={"stage": "applied"}).status_code
            == 404
        )
        assert client.delete("/api/v1/sessions/task-a").status_code == 204
        assert client.delete("/api/v1/sessions/task-b").status_code == 204
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        result = client.get(path).json()
        assert result["stage"] == "applied"
        assert result["note"] == "Reopened"
        assert result["item"]["job"]["job_id"] == JOB_ID
        assert [entry["stage"] for entry in result["history"]] == [
            "applied",
            "interview",
            "closed",
            "applied",
        ]
        assert [item["job_id"] for item in client.get("/api/v1/applications").json()] == [JOB_ID]
        assert client.get("/api/v1/sessions/task-a/feedback").status_code == 404


def test_profile_reuse_and_refresh_preserve_task_conditions_and_answer_evidence(
    tmp_path: Path,
) -> None:
    database = f"sqlite://{(tmp_path / 'reuse.sqlite3').as_posix()}"
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        client.put("/api/v1/profile", json=profile_payload())
        response = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "reuse",
                "use_current_profile": True,
                "target_directions": ["Research"],
                "preferences": {
                    "location_unrestricted": True,
                    "employment_type_unrestricted": True,
                },
            },
        )
        assert response.status_code == 202
        session_id = response.json()["session_id"]
        assert response.json()["profile"]["skills"] == ["SQL"]
        assert response.json()["profile"]["target_directions"] == ["Research"]
        seed(client, "existing")
        updated = profile_payload(1)
        updated["background"]["skills"] = ["Rust"]
        updated["documents"] = []
        assert client.put("/api/v1/profile", json=updated).status_code == 200

        async def check() -> dict[str, Any]:
            state = cast(Any, client.app).state.sessions.sessions["existing"].state
            state["profile_documents"].append(
                SourceDocument(
                    document_id="profile:existing:answer:1",
                    source="user",
                    source_url="",
                    text="Prefer hybrid",
                    fetched_at=NOW,
                )
            )
            changes = await refresh_task_background(state)
            state.update(changes)
            assert await refresh_task_background(state) == {}
            return changes

        changes = cast(Any, client.portal).call(check)
        assert changes["profile"].skills == ["Rust"]
        assert changes["profile"].target_directions == ["Engineer"]
        assert changes["profile"].preferences.location == "Hong Kong"
        assert {doc.text for doc in changes["profile_documents"]} == {
            updated["description"],
            updated["resume"]["text"],
            "Prefer hybrid",
        }
        assert client.get(f"/api/v1/sessions/{session_id}/task").json()["profile_revision"] == 1


def test_import_profile_and_rename_task_keep_raw_material(tmp_path: Path) -> None:
    with TestClient(
        create_app(
            graph=ControlledGraph(),
            database_url=f"sqlite://{(tmp_path / 'import.sqlite3').as_posix()}",
        )
    ) as client:
        seed(client, "task")
        result = client.put(
            "/api/v1/profile/from-session", json={"session_id": "task", "expected_revision": 0}
        )
        assert result.status_code == 200
        assert result.json()["background"]["skills"] == ["Python"]
        assert result.json()["description"] == "Original supplied background"
        assert result.json()["documents"][0]["text"] == "Original supplied background"
        assert (
            client.put(
                "/api/v1/sessions/task/task", json={"title": "My research search"}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/sessions").json()["items"][0]["title"] == "My research search"


def test_reused_background_resolves_new_task_preferences() -> None:
    async def check(unrestricted: bool) -> None:
        provider = MeaningProvider(
            {
                "locations": {"included": ["Hong Kong"], "excluded": []},
                "employment": {"included": ["full-time"], "excluded": []},
            }
        )
        graph = build_live_graph(InMemorySaver(), cast(LLMProvider, provider))
        profile = UserProfile(
            profile_id="task",
            skills=["SQL"],
            target_directions=["Engineer"],
            preferences=ProfilePreferences(
                location=None if unrestricted else "Hong Kong",
                employment_type=None if unrestricted else "full-time",
                location_unrestricted=unrestricted,
                employment_type_unrestricted=unrestricted,
            ),
        )
        result = await graph.nodes["extract"].bound.ainvoke(
            {"session_id": "task", "profile": profile, "input_data": {"use_current_profile": True}}
        )
        normalized = result["profile"]
        assert normalized.skills == ["SQL"]
        assert missing_fields(normalized) == []
        if unrestricted:
            assert normalized.preferences.locations.unrestricted
            assert normalized.preferences.employment.unrestricted
        else:
            assert normalized.preferences.locations.included[0].id == "hk"
            assert normalized.preferences.employment.included == ["full-time"]

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_old_bookmarks_survive_idempotent_table_migration(tmp_path: Path) -> None:
    file = tmp_path / "old.sqlite3"
    database = f"sqlite://{file.as_posix()}"
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        seed(client, "old-task")
        result = client.put(
            f"/api/v1/saved-jobs/{quote(JOB_ID, safe='')}",
            json={"session_id": "old-task", "expected_revision": 1},
        )
        assert result.status_code == 200
    with sqlite3.connect(file) as connection:
        for table in ("career_profile", "career_feedback", "career_applications"):
            connection.execute(f"DROP TABLE {table}")
    for _ in range(2):
        with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
            saved = client.get("/api/v1/saved-jobs").json()["items"]
            assert [item["job"]["job_id"] for item in saved] == [JOB_ID]
            assert client.get("/api/v1/applications").json() == []
            assert client.get("/api/v1/sessions/old-task/feedback").json() == []
            assert client.get("/api/v1/profile").json()["revision"] == 0
    with TestClient(create_app(graph=ControlledGraph(), database_url=database)) as client:
        assert client.delete("/api/v1/sessions/old-task").status_code == 204
        assert client.get("/api/v1/saved-jobs").json()["items"][0]["job"]["job_id"] == JOB_ID
