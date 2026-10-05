"""Integrity and metric checks for the fixed synthetic component benchmark."""

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel
from scripts.evaluate import (
    DATA,
    AuthoredReplayProvider,
    baseline_report,
    evaluate,
    extraction_metrics,
    load_dataset,
    output_path,
    read_json,
    validate_dataset,
    verify_baseline,
)

from jobscout.schemas.profile import UserProfile
from jobscout.services.job_assessment_service import JDAnalysisBatch, MatchingBatch
from jobscout.services.llm_service import get_llm_provider
from jobscout.services.prompts import STRUCTURED_OUTPUT_PROMPT
from tests.test_model_routing import settings


def test_dataset_counts_provenance_and_frozen_baseline() -> None:
    verify_baseline()
    dataset = load_dataset()
    assert len(dataset.profiles) == 12
    assert len(dataset.vacancies) == 30
    assert not dataset.provenance["human_verified"]
    validate_dataset(dataset)


def test_dataset_rejects_unsupported_excerpt() -> None:
    dataset = load_dataset().model_copy(deep=True)
    dataset.vacancies[0].annotations.requirements[0].references[0].excerpt = "fabricated phrase"
    with pytest.raises(ValueError, match="Unsupported requirement"):
        validate_dataset(dataset)


def test_extraction_metrics_and_safe_output_paths() -> None:
    profile = load_dataset().profiles[0].expected_initial
    exact = extraction_metrics(profile, profile)
    assert exact["precision"] == exact["recall"] == 1
    missing = profile.model_copy(update={"skills": []})
    metrics = extraction_metrics(missing, profile)
    assert metrics["false_negative"] == len(profile.skills)
    with pytest.raises(ValueError):
        output_path("README.md")
    with pytest.raises(ValueError):
        output_path(str(DATA / "dataset.json"))


def test_baseline_and_authored_replay_share_candidates_but_not_quality_claims() -> None:
    baseline, _ = asyncio.run(evaluate("baseline"))
    replay, recording = asyncio.run(evaluate("authored-replay"))
    assert baseline["aggregate"]["successful_cases"] == 12
    assert baseline["execution"] == "historical_result"
    assert baseline["latency"]["kind"] == "recorded_baseline"
    assert replay["aggregate"]["successful_cases"] == 12
    assert baseline["dataset_sha256"] == replay["dataset_sha256"]
    assert [row["candidate_sha256"] for row in baseline["cases"]] == [
        row["candidate_sha256"] for row in replay["cases"]
    ]
    assert not replay["measures_model_quality"]
    assert recording is None
    assert replay["usage"]["actual_network_requests"] == 0
    assert replay["latency"]["kind"] == "local_execution_only"


def test_live_recording_uses_both_roles_and_replays_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = read_json(DATA / "replay" / "authored.json")
    delegate: AuthoredReplayProvider | None = None
    requests: list[tuple[str, str, str]] = []
    schemas = {schema.__name__: schema for schema in (UserProfile, JDAnalysisBatch, MatchingBatch)}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delegate
        body = json.loads(request.content)
        messages = body["messages"][1:]
        payload = json.loads(messages[-1]["content"])
        if payload["task"] == "evaluation_profile":
            delegate = AuthoredReplayProvider(fixture, payload["profile_id"])
        assert delegate is not None
        schema_name = json.loads(
            body["messages"][0]["content"].removeprefix(STRUCTURED_OUTPUT_PROMPT)
        )["title"]
        result: BaseModel
        if schema_name == "MatchingBatch":
            result = MatchingBatch.model_validate(
                {
                    "jobs": [
                        {
                            "job_id": job["job_id"],
                            "matches": [
                                {
                                    "requirement_id": requirement["requirement_id"],
                                    "level": "not_documented",
                                }
                                for requirement in job["requirements"]
                            ],
                        }
                        for job in payload["jobs"]
                    ]
                }
            )
        else:
            result = await delegate.structured(schemas[schema_name], messages)
        requests.append((schema_name, str(request.url), body["model"]))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": result.model_dump_json()}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    client_factory = httpx.AsyncClient
    monkeypatch.setattr(
        "jobscout.services.llm_service.httpx.AsyncClient",
        lambda: client_factory(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "jobscout.services.llm_service.get_llm_provider", lambda _: get_llm_provider(settings())
    )
    report, recording = asyncio.run(evaluate("live"))
    assert report["aggregate"]["successful_cases"] == 12
    assert report["usage"]["provider_structured_calls"] == len(requests)
    assert report["usage"]["actual_network_requests"] == len(requests)
    assert report["usage"]["model_usage"]["total_tokens"] == len(requests) * 5
    assert recording is not None
    assert recording["provenance"]["models"] == {
        "semantic": "synthetic-semantic",
        "decision": "synthetic-decision",
    }
    assert {row["model_role"] for row in recording["responses"]} == {"semantic", "decision"}
    for schema, url, model in requests:
        role = "decision" if schema == "MatchingBatch" else "semantic"
        version = "v2" if role == "decision" else "v1"
        assert url == f"https://{role}.example.invalid/{version}/chat/completions"
        assert model == f"synthetic-{role}"
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    replay, _ = asyncio.run(evaluate("recorded-replay", path))
    assert replay["aggregate"]["successful_cases"] == 12
    assert len(requests) == report["usage"]["actual_network_requests"]
    assert [row["recommended_ids"] for row in replay["cases"]] == [
        row["recommended_ids"] for row in report["cases"]
    ]
    assert [row["ranking"] for row in replay["cases"]] == [
        row["ranking"] for row in report["cases"]
    ]


def test_historical_baseline_rejects_modified_report(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    shutil.copyfile(DATA / "manifest.json", tmp_path / "manifest.json")
    (tmp_path / "results" / "baseline.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_baseline(tmp_path)


def test_historical_baseline_rejects_changed_candidates() -> None:
    dataset = load_dataset().model_copy(deep=True)
    dataset.profiles[0].candidate_ids.reverse()
    with pytest.raises(ValueError, match="evaluation candidates"):
        baseline_report(dataset)
    with pytest.raises(ValueError):
        output_path(str(DATA / "results" / "baseline.json"))
