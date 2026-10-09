"""Validate exclusion matches and merge accumulated recommendations without changing IDs."""

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from jobscout.schemas.feedback import FeedbackModel, HiddenJobReason, ResultPreferences
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import ProfilePreferences
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.services.job_processing_service import job_identity, merge_postings
from jobscout.services.llm_service import LLMProvider, ModelServiceError
from jobscout.services.location_service import get_location_catalog, within
from jobscout.services.notice_service import dedupe_notices
from jobscout.services.prompts import RESULT_EXCLUSION_PROMPT

SUPPLEMENTARY_RESULT_LIMIT = 5


class ExclusionMatch(FeedbackModel):
    job_id: str
    exclusion_id: str
    decision: Literal["matches", "does_not_match", "unknown"]
    quotes: list[str] = Field(default_factory=list)


class ExclusionMatches(FeedbackModel):
    matches: list[ExclusionMatch] = Field(default_factory=list)


def job_content(job: JobPosting) -> str:
    return "\n".join(
        [
            job.title,
            job.company,
            job.location,
            job.employment_type or "",
            job.salary or "",
            job.description,
            *job.responsibilities,
            *job.required_skills,
            *(document.text for document in job.source_documents),
        ]
    )


def match_key(job: JobPosting, exclusion_id: str, description: str) -> str:
    content_hash = hashlib.sha256(job_content(job).encode()).hexdigest()
    return json.dumps([job.job_id, exclusion_id, description, content_hash])


def merge_results(
    previous: RecommendationResult | None,
    incoming: RecommendationResult,
    order: list[str],
    *,
    baseline_job_ids: list[str] | None = None,
) -> tuple[RecommendationResult, list[str]]:
    items = list(previous.jobs + previous.pending_jobs) if previous else []
    by_id = {item.job.job_id: item for item in items}
    reviewed_ids = {item.job.job_id for item in previous.jobs} if previous else set()
    incoming_reviewed = {item.job.job_id for item in incoming.jobs}
    identities = {job_identity(item.job): item.job.job_id for item in items}
    next_order = list(dict.fromkeys([*order, *(item.job.job_id for item in items)]))
    remaining = (
        max(0, SUPPLEMENTARY_RESULT_LIMIT - len(set(by_id) - set(baseline_job_ids)))
        if baseline_job_ids is not None
        else None
    )
    for item in [*incoming.jobs, *incoming.pending_jobs]:
        job = item.job
        stable_id = job.job_id if job.job_id in by_id else identities.get(job_identity(job))
        if stable_id is None:
            if remaining is not None:
                if remaining == 0:
                    continue
                remaining -= 1
            stable_id = job.job_id
            by_id[stable_id] = item.model_copy(deep=True)
            identities[job_identity(job)] = stable_id
            if job.job_id in incoming_reviewed:
                reviewed_ids.add(stable_id)
            next_order.append(stable_id)
            continue
        old = by_id[stable_id]
        combined = merge_postings(old.job, job).model_copy(update={"job_id": stable_id})
        # Keep a completed review when a later source only supplies a queued duplicate.
        chosen = (
            old if old.review_status == "reviewed" and item.review_status != "reviewed" else item
        )
        if chosen is item:
            if item.job.job_id in incoming_reviewed:
                reviewed_ids.add(stable_id)
            else:
                reviewed_ids.discard(stable_id)
        by_id[stable_id] = chosen.model_copy(deep=True, update={"job": combined})
    next_order = [identity for identity in dict.fromkeys(next_order) if identity in by_id]
    jobs = [by_id[identity] for identity in next_order if identity in reviewed_ids]
    pending = [by_id[identity] for identity in next_order if identity not in reviewed_ids]
    notices = dedupe_notices([*(previous.notices if previous else []), *incoming.notices])
    return incoming.model_copy(
        update={"jobs": jobs, "pending_jobs": pending, "notices": notices}
    ), next_order


def refresh_hidden(state: dict[str, Any]) -> None:
    recommendation = state.get("recommendation")
    preferences = ResultPreferences.model_validate(state.get("result_preferences", {}))
    cache = state.get("exclusion_matches", {})
    reasons: list[HiddenJobReason] = []
    if recommendation:
        items = recommendation.jobs + recommendation.pending_jobs
        ids = {item.job.job_id for item in items}
        state["result_order"] = list(
            dict.fromkeys(
                [
                    *(identity for identity in state.get("result_order", []) if identity in ids),
                    *(item.job.job_id for item in items),
                ]
            )
        )
        for feedback in state.get("job_feedback", []):
            if feedback.job_id in ids and feedback.reaction == "not_interested":
                reasons.append(HiddenJobReason(job_id=feedback.job_id, kind="not_interested"))
        for item in items:
            for rule in preferences.exclusions:
                key = match_key(item.job, rule.exclusion_id, rule.description)
                if cache.get(key, {}).get("decision") == "matches":
                    reasons.append(
                        HiddenJobReason(
                            job_id=item.job.job_id, kind="excluded", exclusion_id=rule.exclusion_id
                        )
                    )
    state["hidden_job_reasons"] = reasons
    state["hidden_job_ids"] = list(dict.fromkeys(reason.job_id for reason in reasons))


class ResultFeedbackService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def classify(
        self,
        jobs: list[JobPosting],
        preferences: ResultPreferences,
        cache: dict[str, Any],
        *,
        deadline: float,
        conditions: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[set[str], dict[str, Any]]:
        if not preferences.exclusions:
            return set(), {}
        updated = dict(cache)
        catalog = getattr(self.provider, "location_catalog", None) or get_location_catalog()
        for job in jobs:
            for rule in preferences.exclusions:
                condition = (conditions or {}).get(rule.exclusion_id)
                key = match_key(job, rule.exclusion_id, rule.description)
                if not condition or key in updated:
                    continue
                parsed = ProfilePreferences.model_validate(condition)
                decision: str | None = None
                quote = ""
                locations = [*parsed.locations.included, *parsed.locations.excluded]
                employment = [*parsed.employment.included, *parsed.employment.excluded]
                if locations:
                    actual = catalog.find(job.location)
                    if len(actual) == 1:
                        if any(within(actual[0], place) for place in locations):
                            decision = "matches"
                        elif not any(within(place, actual[0]) for place in locations):
                            decision = "does_not_match"
                        quote = job.location
                elif employment and job.employment_type:
                    decision = "matches" if job.employment_type in employment else "does_not_match"
                    quote = job.employment_type
                if decision is not None:
                    updated[key] = {
                        "job_id": job.job_id,
                        "exclusion_id": rule.exclusion_id,
                        "decision": decision,
                        "quotes": [quote],
                    }
        for offset in range(0, len(jobs), 10):
            batch = jobs[offset : offset + 10]
            pairs = {
                (job.job_id, rule.exclusion_id): (job, rule)
                for job in batch
                for rule in preferences.exclusions
                if match_key(job, rule.exclusion_id, rule.description) not in updated
            }
            if not pairs:
                continue
            payload = {
                "task": "result_exclusions",
                "jobs": [{"job_id": job.job_id, "content": job_content(job)} for job in batch],
                "exclusions": [rule.model_dump() for rule in preferences.exclusions],
                "pairs": [{"job_id": job_id, "exclusion_id": rule_id} for job_id, rule_id in pairs],
            }
            output = await self.provider.structured(
                ExclusionMatches,
                [
                    {"role": "system", "content": RESULT_EXCLUSION_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                deadline=deadline,
            )
            seen: set[tuple[str, str]] = set()
            for result in output.matches:
                pair = result.job_id, result.exclusion_id
                if pair not in pairs or pair in seen:
                    raise ModelServiceError("model_output")
                seen.add(pair)
                job, rule = pairs[pair]
                if result.decision != "unknown" and (
                    not result.quotes
                    or any(
                        not quote.strip() or quote not in job_content(job)
                        for quote in result.quotes
                    )
                ):
                    raise ModelServiceError("model_output")
                updated[match_key(job, rule.exclusion_id, rule.description)] = result.model_dump()
            for pair, (job, rule) in pairs.items():
                if pair not in seen:
                    updated[match_key(job, rule.exclusion_id, rule.description)] = {
                        "decision": "unknown"
                    }
        blocked = {
            job.job_id
            for job in jobs
            for rule in preferences.exclusions
            if updated.get(match_key(job, rule.exclusion_id, rule.description), {}).get("decision")
            == "matches"
        }
        valid = {
            match_key(job, rule.exclusion_id, rule.description)
            for job in jobs
            for rule in preferences.exclusions
        }
        # Retain other jobs' entries; discard old content versions of the supplied jobs.
        ids = {job.job_id for job in jobs}
        updated = {
            key: value
            for key, value in updated.items()
            if json.loads(key)[0] not in ids or key in valid
        }
        return blocked, updated
