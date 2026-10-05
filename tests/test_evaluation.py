"""Integrity and metric checks for the fixed synthetic component benchmark."""

import asyncio

import pytest
from scripts.evaluate import (
    DATA,
    AuthoredReplayProvider,
    evaluate,
    extraction_metrics,
    load_dataset,
    output_path,
    read_json,
    validate_dataset,
    verify_baseline,
)


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
    assert replay["aggregate"]["successful_cases"] == 12
    assert baseline["dataset_sha256"] == replay["dataset_sha256"]
    assert [row["candidate_sha256"] for row in baseline["cases"]] == [
        row["candidate_sha256"] for row in replay["cases"]
    ]
    assert not replay["quality_evidence"]
    assert recording is None
    assert replay["usage"]["actual_network_requests"] == 0
    assert replay["latency"]["kind"] == "local_execution_only"


def test_authored_provider_is_visibly_not_a_live_model() -> None:
    provider = AuthoredReplayProvider(read_json(DATA / "replay" / "authored.json"), "unused")
    assert provider.model == "authored-fixture-not-a-model"
