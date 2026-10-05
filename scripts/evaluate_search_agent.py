"""Paired retrieval-policy evaluation on explicitly synthetic source snapshots.

Both policies execute the production SearchAgent and JobAssessmentService with the
same tools, profiles, budgets and isolated caches. Live mode uses real model calls
for assessment/review in both arms and native decisions in the adaptive arm.
Authored replay checks orchestration only; it is not model-quality evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from jobscout.config import get_settings
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.model import ModelUsage
from jobscout.schemas.profile import LocationRef, UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_assessment_service import JobAssessmentService
from jobscout.services.job_retrieval.models import (
    RawJob,
    SearchResult,
    SourceOutcome,
    workflow_error,
)
from jobscout.services.llm_service import ToolCall, ToolTurn, get_llm_provider
from jobscout.services.location_service import CatalogEntry, LocationCatalog
from jobscout.services.search_agent import SearchAgent

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/evaluation/search_scenarios.json"
type Json = dict[str, Any]
type Mode = Literal["authored-replay", "live"]
STAMP = datetime(2026, 10, 6, tzinfo=UTC)
PROFILE_DOCUMENTS = {
    "description": "Synthetic applicant: I built React applications and SQL reports."
}


def catalog() -> LocationCatalog:
    return LocationCatalog(
        entries=[
            CatalogEntry(
                LocationRef(
                    id="hk:district:01",
                    name="Central and Western",
                    region="hk",
                    level="district",
                    parent_id="hk",
                    ancestor_ids=["hk"],
                ),
                {"Central and Western", "中西区", "中西區"},
                "https://snapshot.example/geography",
            )
        ]
    )


def profile_for(case: Json, directory: LocationCatalog) -> UserProfile:
    place = directory.find(case["location"])[0]
    return UserProfile.model_validate(
        {
            "profile_id": case["id"],
            "skills": ["React", "SQL"],
            "projects": [PROFILE_DOCUMENTS["description"]],
            "target_directions": case["directions"],
            "search_options": {"result_count": case["target_count"]},
            "confirmed_fields": [
                "target_directions",
                "preferences.location",
                "preferences.employment_type",
            ],
            "preferences": {
                "location": case["location"],
                "employment_type": " or ".join(case["employment_included"]),
                "locations": {"raw_text": case["location"], "included": [place.model_dump()]},
                "employment": {
                    "raw_text": " or ".join(case["employment_included"]),
                    "included": case["employment_included"],
                    "excluded": case["employment_excluded"],
                },
            },
        }
    )


class SnapshotSearch:
    """Read-only source snapshots; missing queries return empty, never live network."""

    def __init__(self, case: Json) -> None:
        self.case = case
        self.supported_sources = case["sources"]
        self.jobs = {row["id"]: row for row in case["jobs"]}
        self.calls: list[Json] = []

    def source_url(self, job_id: str) -> str:
        return f"https://snapshot.example/jobs/{self.case['id']}/{job_id}"

    def identity(self, url: str) -> str:
        return url.rsplit("/", 1)[-1]

    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60
    ) -> SearchResult:
        result = SearchResult()
        for index, request in enumerate(requests):
            source = request.sources[0]
            self.calls.append(
                {
                    "tool": "search_jobs",
                    "source": source,
                    "direction": request.target_direction,
                    "page": request.page,
                    "keywords": request.keywords,
                }
            )
            keywords = " ".join(request.keywords).casefold()
            rows = [
                row
                for row in self.case["pages"]
                if row["source"] == source
                and row["page"] == request.page
                and row["direction"] == request.target_direction
                and (row["keyword"] is None or row["keyword"].casefold() in keywords)
            ]
            page: Json = rows[-1] if rows else {"status": "empty", "job_ids": []}
            if page["status"] == "blocked":
                result.errors.append(
                    workflow_error(
                        "SEARCH_SOURCE_BLOCKED", "Synthetic source unavailable.", source=source
                    )
                )
            for job_id in page["job_ids"]:
                job = self.jobs[job_id]
                result.raw_jobs.append(
                    RawJob(
                        source=job["source"],
                        source_url=self.source_url(job_id),
                        source_job_id=job_id,
                        title=job["title"],
                        company=f"Synthetic Company {job_id}",
                        location=job["location"],
                        employment_type=job["employment_type"],
                        description=job["description"],
                        description_is_excerpt=job["detail_description"] is not None,
                        target_direction=request.target_direction,
                        fetched_at=STAMP,
                        expiry_at="2020-01-01T00:00:00Z" if job["expired"] else None,
                        raw_payload={},
                    )
                )
            result.outcomes.append(
                SourceOutcome(
                    request_index=index,
                    target_direction=request.target_direction,
                    source=source,
                    candidate_count=len(page["job_ids"]),
                    returned_count=len(page["job_ids"]),
                    status=page["status"],
                )
            )
        return result

    async def fetch_details(
        self, jobs: list[JobPosting], *, timeout: float = 30
    ) -> list[JobPosting]:
        self.calls.append(
            {
                "tool": "fetch_job_details",
                "job_ids": [self.identity(job.source_url) for job in jobs],
            }
        )
        result = []
        for job in jobs:
            text = self.jobs[self.identity(job.source_url)]["detail_description"]
            if text:
                job = job.model_copy(
                    update={
                        "description": text,
                        "description_is_excerpt": False,
                        "source_documents": [
                            SourceDocument(
                                document_id=f"details:{job.job_id}",
                                source=job.source,
                                source_url=job.source_url,
                                text=text,
                                fetched_at=STAMP,
                            )
                        ],
                    },
                    deep=True,
                )
            result.append(job)
        return result


class PolicyProvider:
    """Scripted decisions are an experimental control, never a production fallback."""

    def __init__(self, case: Json, mode: Mode, policy: str) -> None:
        self.case, self.mode, self.policy = case, mode, policy
        self.location_catalog = catalog()
        self.delegate = get_llm_provider(get_settings()) if mode == "live" else None
        self.model = self.delegate.model if self.delegate else "authored-synthetic-replay"
        self.cache_identity = self.delegate.cache_identity if self.delegate else self.model
        self.tool_calls: list[Json] = []
        self.decisions = 0

    @contextmanager
    def usage_scope(self) -> Iterator[ModelUsage]:
        if self.delegate:
            with self.delegate.usage_scope() as usage:
                yield usage
        else:
            yield ModelUsage()

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        if self.delegate and self.policy == "adaptive":
            turn = await self.delegate.tool_turn(messages, tools, deadline=deadline)
        else:
            turn = self.scripted_turn(
                json.loads(messages[1]["content"]), json.loads(messages[-1]["content"])
            )
        self.decisions += 1
        self.tool_calls.extend(
            {"name": call.name, "arguments": call.arguments} for call in turn.calls
        )
        return turn

    def scripted_turn(self, initial: Json, observation: Json) -> ToolTurn:
        args: Json
        candidates = [row for row in observation["candidates"] if not row["analysis_attempts"]]
        detail_ids = [row["job_id"] for row in candidates if row["needs_details"]]
        if observation["matched_count"] >= observation["result_limit"]:
            return ToolTurn(
                calls=[
                    ToolCall(
                        id=f"scripted-{self.decisions}",
                        name="finish_search",
                        arguments={"reason": "target_reached"},
                    )
                ]
            )
        if self.policy == "adaptive" and detail_ids:
            name, args = "fetch_job_details", {"job_ids": detail_ids[:10]}
        elif candidates and observation["remaining_candidates"]:
            name, args = (
                "assess_candidates",
                {"job_ids": [row["job_id"] for row in candidates[:10]]},
            )
        else:
            queries = observation["queries"]
            pairs = [
                (direction, source)
                for direction in initial["confirmed_profile"]["target_directions"]
                for source in initial["available_sources"]
            ]
            next_query: Json | None = None
            if self.policy == "fixed":
                # Two predefined pages per source/direction; never chooses detail enrichment.
                plans = [
                    {
                        "direction": direction,
                        "source": source,
                        "keywords": [direction],
                        "page": page,
                    }
                    for page in (1, 2)
                    for direction, source in pairs
                ]
                next_query = next(
                    (
                        plan
                        for plan in plans
                        if not any(
                            all(query[key] == plan[key] for key in plan) for query in queries
                        )
                    ),
                    None,
                )
            else:
                for direction, source in pairs:
                    previous = [
                        query
                        for query in queries
                        if query["direction"] == direction and query["source"] == source
                    ]
                    if not previous:
                        next_query = {
                            "direction": direction,
                            "source": source,
                            "keywords": [direction],
                            "page": 1,
                        }
                        break
                    last = previous[-1]
                    if last["new_jobs"] and last["page"] < 5:
                        next_query = {
                            "direction": direction,
                            "source": source,
                            "keywords": [direction],
                            "page": last["page"] + 1,
                        }
                        break
                    if (
                        not last["new_jobs"]
                        and not any("React" in query["keywords"] for query in previous)
                        and not any(outcome["status"] == "blocked" for outcome in last["outcomes"])
                    ):
                        next_query = {
                            "direction": direction,
                            "source": source,
                            "keywords": ["React"],
                            "page": 1,
                        }
                        break
            if next_query:
                name, args = "search_jobs", next_query
            else:
                name, args = "finish_search", {"reason": "source_exhausted"}
        return ToolTurn(
            calls=[ToolCall(id=f"scripted-{self.decisions}", name=name, arguments=args)]
        )

    async def structured[T: BaseModel](
        self, schema: type[T], messages: list[dict[str, str]], *, deadline: float | None = None
    ) -> T:
        if self.delegate:
            return await self.delegate.structured(schema, messages, deadline=deadline)
        payload = json.loads(messages[-1]["content"])
        rows = []
        for job in payload["jobs"]:
            row: Json = {"job_id": job["job_id"]}
            if payload["task"] == "matching":
                row["matches"] = [
                    {
                        "requirement_id": requirement["requirement_id"],
                        "level": "strong",
                        "profile_source_quotes": [
                            {"document_id": "description", "excerpt": requirement["text"]}
                        ],
                        "profile_fact_ids": [
                            identity
                            for identity, fact in payload["profile_facts"].items()
                            if fact["text"] == requirement["text"]
                        ],
                    }
                    for requirement in job["requirements"]
                ]
                row["preparation_suggestions"] = []
            else:
                documents = job["documents"]
                if payload["task"] == "jd_analysis":
                    row["requirements"] = []
                    for skill in ("React", "SQL"):
                        document = next(
                            (
                                doc
                                for doc in documents
                                if f"{skill} experience is required" in doc["text"]
                            ),
                            None,
                        )
                        if document:
                            row["requirements"].append(
                                {
                                    "requirement_id": skill,
                                    "text": skill,
                                    "skill_terms": [skill],
                                    "category": "skill",
                                    "source_quotes": [
                                        {"document_id": document["document_id"], "excerpt": skill}
                                    ],
                                }
                            )
                if payload["task"] == "jd_analysis":
                    row.update(
                        {
                            "locations": [],
                            "employment": [],
                            "direction": "unknown",
                            "direction_quotes": [],
                        }
                    )
                    for place in ("Central and Western", "Hong Kong"):
                        document = next((doc for doc in documents if place in doc["text"]), None)
                        if document:
                            row["locations"].append(
                                {
                                    "query": place,
                                    "source_quotes": [
                                        {"document_id": document["document_id"], "excerpt": place}
                                    ],
                                }
                            )
                            break
                    for kind in ("full-time", "internship", "contract"):
                        document = next((doc for doc in documents if kind in doc["text"]), None)
                        if document:
                            row["employment"].append(
                                {
                                    "value": kind,
                                    "source_quotes": [
                                        {"document_id": document["document_id"], "excerpt": kind}
                                    ],
                                }
                            )
                    for title in ("Sales Representative", "Frontend Developer", "Data Analyst"):
                        document = next((doc for doc in documents if title in doc["text"]), None)
                        if document:
                            row["direction"] = (
                                "match" if title in payload["target_directions"] else "mismatch"
                            )
                            row["direction_quotes"] = [
                                {"document_id": document["document_id"], "excerpt": title}
                            ]
                            break
            rows.append(row)
        return schema.model_validate({"jobs": rows})


def metrics(case: Json, result: RecommendationResult) -> Json:
    truth = {job["id"]: job for job in case["jobs"]}
    reachable = {
        job_id
        for page in case["pages"]
        if page["status"] != "blocked"
        for job_id in page["job_ids"]
    }
    relevant = {
        key
        for key, row in truth.items()
        if key in reachable
        and row["relevant"]
        and not row["hard_violations"]
        and not row["pending"]
    }
    returned = [item.job.source_url.rsplit("/", 1)[-1] for item in result.jobs]
    correct = set(returned) & relevant
    violations = {
        key: truth[key]["hard_violations"]
        for key in returned
        if key in truth and truth[key]["hard_violations"]
    }
    quote_total = quote_correct = 0
    for item in [*result.jobs, *result.pending_jobs]:
        documents = {doc.document_id: doc.text for doc in item.job.source_documents}
        for reason in item.matching_reasons:
            for quote, texts in [
                *((quote, documents) for quote in reason.job_source_quotes),
                *((quote, PROFILE_DOCUMENTS) for quote in reason.profile_source_quotes),
            ]:
                quote_total += 1
                quote_correct += bool(
                    quote.excerpt and quote.excerpt in texts.get(quote.document_id, "")
                )
    visible = [*result.jobs, *result.pending_jobs]
    visible_ids = {item.job.source_url.rsplit("/", 1)[-1] for item in visible}
    useful = {
        key
        for key, row in truth.items()
        if key in reachable and row["relevant"] and not row["hard_violations"]
    }
    coverage = {truth[key]["direction"] for key in correct}
    return {
        "display_limit_filled": len(visible_ids) >= case["target_count"],
        "useful_results_count": len(visible_ids & useful),
        "visible_relevant_recall": len(visible_ids & useful) / len(useful) if useful else None,
        "analysis_completion_rate": sum(item.analysis_status == "complete" for item in visible)
        / len(visible)
        if visible
        else None,
        "returned_job_ids": returned,
        "pending_job_ids": [item.job.source_url.rsplit("/", 1)[-1] for item in result.pending_jobs],
        "precision_at_n": len(correct) / len(returned) if returned else None,
        "relevant_recall": len(correct) / len(relevant) if relevant else None,
        "hard_condition_violations": violations,
        "citation_correctness": quote_correct / quote_total if quote_total else None,
        "citation_count": quote_total,
        "direction_coverage": len(coverage) / len(case["directions"]),
    }


async def run_policy(case: Json, mode: Mode, policy: str, budget: float = 300) -> Json:
    provider = PolicyProvider(case, mode, policy)
    search = SnapshotSearch(case)
    profile = profile_for(case, provider.location_catalog)
    assessment = JobAssessmentService(
        provider, decision_provider=provider.delegate.decision if provider.delegate else provider
    )
    identity = f"evaluation-{case['id']}-{policy}"
    await assessment.begin_search(identity)
    started = time.monotonic()
    first_result_seconds: float | None = None
    first_analysis_seconds: float | None = None

    async def progress(update: Json) -> None:
        nonlocal first_result_seconds, first_analysis_seconds
        result = update["recommendation"]
        visible = [*result.jobs, *result.pending_jobs]
        elapsed = round(time.monotonic() - started, 3)
        if visible and first_result_seconds is None:
            first_result_seconds = elapsed
        if (
            any(item.analysis_status != "unavailable" for item in visible)
            and first_analysis_seconds is None
        ):
            first_analysis_seconds = elapsed

    state = await SearchAgent(provider, search, assessment).run(
        profile,
        PROFILE_DOCUMENTS,
        identity,
        deadline=asyncio.get_running_loop().time() + budget,
        on_progress=progress,
    )
    return {
        "scenario": case["id"],
        "policy": policy,
        "mode": mode,
        "models": (
            provider.delegate.models
            if provider.delegate
            else {"semantic": provider.model, "decision": provider.model}
        ),
        "stop_reason": state["stop_reason"],
        "error_code": state.get("agent_error_code"),
        "latency_seconds": round(time.monotonic() - started, 3),
        "first_result_seconds": first_result_seconds,
        "first_analysis_seconds": first_analysis_seconds,
        "tool_call_count": len(provider.tool_calls),
        "tool_calls": provider.tool_calls,
        "model_usage": state["model_usage"],
        **metrics(case, state["recommendation"]),
    }


async def evaluate(
    mode: Mode, *, limit: int | None = None, budget: float = 300, concurrency: int = 2
) -> Json:
    raw = DATA.read_bytes()
    source_paths = [
        "scripts/evaluate_search_agent.py",
        "src/jobscout/services/search_agent.py",
        "src/jobscout/services/tool_registry.py",
        "src/jobscout/services/job_assessment_service.py",
        "src/jobscout/services/prompts.py",
        "src/jobscout/services/job_processing_service.py",
        "src/jobscout/services/recommendation_service.py",
        "src/jobscout/services/llm_service.py",
        "src/jobscout/services/location_service.py",
        "src/jobscout/schemas/profile.py",
        "src/jobscout/schemas/recommendation.py",
    ]
    implementation_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_paths
    }
    dataset = json.loads(raw)
    cases = dataset["scenarios"][:limit]
    semaphore = asyncio.Semaphore(concurrency)

    async def paired(case: Json) -> Json:
        async with semaphore:
            results = [
                await run_policy(case, mode, policy, budget) for policy in ("fixed", "adaptive")
            ]
            print(f"Completed synthetic scenario {case['id']} ({mode}).", flush=True)
            return {"scenario": case["id"], "results": results}

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "implementation_sha256": implementation_hashes,
        "provenance": dataset["provenance"],
        "model_quality_evidence": mode == "live",
        "metric_definitions": {
            "precision_at_n": "Relevant, hard-condition-compliant returned matches divided by returned matches (not padded to the target); null when no matches.",
            "relevant_recall": "Correct returned identities divided by relevant confirmed identities reachable in at least one nonblocked source snapshot.",
            "citation_correctness": "Exact excerpt presence in the referenced original document only; this does not measure semantic entailment or claim correctness.",
            "display_limit_filled": "The visible shortlist fills the requested display limit; this measures quantity, not usefulness.",
            "useful_results_count": "Visible relevant jobs without known hard-condition violations, including jobs labeled with unknown conditions.",
            "visible_relevant_recall": "Useful visible identities divided by reachable useful identities, including pending jobs.",
            "analysis_completion_rate": "Visible jobs with complete personal analysis divided by all visible jobs; null for no results.",
            "first_result_seconds": "Time until the first source-backed job can be displayed, before analysis if necessary.",
            "first_analysis_seconds": "Time until the first visible job has complete or partial personal analysis.",
            "direction_coverage": "Confirmed requested directions represented by correct returned matches divided by requested directions.",
        },
        "comparison": "Same production agent loop, assessment service, source snapshots, semantic and decision models, 12-decision and candidate budgets; isolated providers, catalog and caches. Fixed control searches two predetermined pages and never enriches details. Adaptive live arm uses native model tool decisions.",
        "budget_seconds_per_run": budget,
        "pairs": await asyncio.gather(*(paired(case) for case in cases)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["authored-replay", "live"], default="authored-replay")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--budget", type=float, default=300)
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.budget <= 300 or args.limit is not None and args.limit < 1:
        parser.error("Use a positive limit and a budget from 0 to 300 seconds.")
    report = asyncio.run(
        evaluate(args.mode, limit=args.limit, budget=args.budget, concurrency=args.concurrency)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved {len(report['pairs'])} paired scenarios to {args.output}.")


if __name__ == "__main__":
    main()
