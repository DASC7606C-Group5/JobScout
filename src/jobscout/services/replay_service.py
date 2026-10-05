"""Explicit synthetic demo mode, never a fallback for live services."""

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.models import RawJob, SearchResult, SourceOutcome

DATA = Path(__file__).resolve().parents[3] / "data" / "evaluation" / "dataset.json"


@lru_cache(maxsize=1)
def _dataset() -> dict[str, Any]:
    return dict(json.loads(DATA.read_text(encoding="utf-8")))


def _profile_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    """Replay background facts for an exact sample; never parse arbitrary CVs."""
    description = payload.get("description", "").strip()
    resume_text = (payload.get("resume") or {}).get("text", "").strip()
    for case in _dataset()["profiles"]:
        sample = case["input"]
        if (
            sample.get("description", "").strip() == description
            and (sample.get("resume") or {}).get("text", "").strip() == resume_text
        ):
            return {
                field: case["expected_initial"][field]
                for field in ("education", "skills", "internships", "projects", "conflicts")
            }
    return {}


def _payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    return dict(json.loads(messages[-1]["content"]))


class ReplayProvider:
    model = "synthetic-replay-not-a-live-model"

    async def structured[T: BaseModel](
        self,
        schema: type[T],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> T:
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Replay deadline exhausted")
        payload = _payload(messages)
        name = schema.__name__
        if name == "ProfileExtraction":
            output: dict[str, Any] = _profile_fixture(payload)
        elif name == "QuestionGeneration":
            output = {"questions": []}
            for field in payload.get("required_fields", [])[:3]:
                options: list[dict[str, str]] = []
                control = "text"
                if field == "target_directions":
                    control = "multiple_choice"
                    options = [
                        {"id": role, "label": role}
                        for role in (
                            "Data Analyst",
                            "Frontend Developer",
                            "Business Analyst",
                        )
                    ]
                elif field == "preferences.location":
                    control = "single_choice"
                    options = [
                        {"id": key, "label": label}
                        for key, label in (
                            ("Hong Kong", "Hong Kong"),
                            ("Shenzhen", "Shenzhen"),
                            ("unrestricted", "Any location"),
                        )
                    ]
                elif field == "preferences.employment_type":
                    control = "single_choice"
                    options = [
                        {"id": key, "label": label}
                        for key, label in (
                            ("internship", "Internship"),
                            ("full-time", "Full-time"),
                            ("part-time", "Part-time"),
                            ("unrestricted", "Any employment type"),
                        )
                    ]
                label = {
                    "target_directions": "Choose up to three job directions.",
                    "preferences.location": "Where would you like to work?",
                    "preferences.employment_type": "What type of employment are you looking for?",
                }.get(field, f"Please provide information for {field}.")
                output["questions"].append(
                    {
                        "field": field,
                        "question": label,
                        "reason": "This must be clear before we search.",
                        "control_type": control,
                        "options": options,
                    }
                )
        elif name == "AnswerInterpretation":
            output = {"changes": []}
            message = payload.get("message", "")
            for field, pattern in (
                ("preferences.location", r"(?:地点|location)\s*[:：]\s*([^\n,，;；]+)"),
                (
                    "preferences.employment_type",
                    r"(?:类型|employment type)\s*[:：]\s*([^\n,，;；]+)",
                ),
            ):
                match = re.search(pattern, message, re.IGNORECASE)
                if match:
                    output["changes"].append({"field": field, "value": match.group(1).strip()})
        elif name == "SearchPhrasing":
            output = {
                "phrases": [
                    {"direction": direction, "source": source, "phrase": direction}
                    for direction, source in payload["pairs"]
                ]
            }
        elif payload.get("task") == "jd_analysis":
            output = {"jobs": []}
            for job in payload["jobs"]:
                requirements: list[dict[str, Any]] = []
                for sample in _dataset()["vacancies"]:
                    if not any(
                        document["source_url"] == sample["job"]["source_url"]
                        for document in job["documents"]
                    ):
                        continue
                    for requirement in sample["annotations"]["requirements"]:
                        source_quotes = [
                            {"document_id": document["document_id"], "excerpt": ref["excerpt"]}
                            for ref in requirement["references"]
                            for document in job["documents"]
                            if document["source_url"] == ref["source_url"]
                            and ref["excerpt"] in document["text"]
                        ]
                        if source_quotes:
                            requirements.append(
                                {
                                    "requirement_id": requirement["requirement_id"],
                                    "text": requirement["text"],
                                    "category": "skill",
                                    "source_quotes": source_quotes,
                                }
                            )
                output["jobs"].append({"job_id": job["job_id"], "requirements": requirements})
        elif payload.get("task") == "matching":
            output = {"jobs": []}
            profile = payload["profile"]
            documents = payload["profile_documents"]
            skills = {value.casefold() for value in profile["skills"]}
            for job in payload["jobs"]:
                matches = []
                suggestions = []
                for requirement in job["requirements"]:
                    text = requirement["text"]
                    ref = next(
                        (
                            {"document_id": doc_id, "excerpt": text}
                            for doc_id, content in documents.items()
                            if text in content
                        ),
                        None,
                    )
                    strong = text.casefold() in skills and ref is not None
                    matches.append(
                        {
                            "requirement_id": requirement["requirement_id"],
                            "level": "strong" if strong else "not_documented",
                            "profile_source_quotes": [ref] if strong else [],
                            "experience_source_quotes": [],
                        }
                    )
                    suggestions.append(
                        {"requirement_id": requirement["requirement_id"], "action": "practice"}
                    )
                output["jobs"].append(
                    {
                        "job_id": job["job_id"],
                        "matches": matches,
                        "preparation_suggestions": suggestions[:10],
                    }
                )
        else:
            raise ValueError("Unsupported replay schema; no live fallback")
        return schema.model_validate(output)


class ReplaySearchService:
    async def search_many_async(
        self,
        requests: list[SearchRequest],
        *,
        timeout: float = 60.0,
    ) -> SearchResult:
        if timeout <= 0:
            raise TimeoutError("Replay retrieval deadline exhausted")
        dataset = _dataset()
        result = SearchResult(
            warnings=["Replay demo: these are sample listings, not real job postings."]
        )
        for index, request in enumerate(requests):
            selected = []
            for row in dataset["vacancies"]:
                job = row["job"]
                if job["target_direction"].casefold() != request.target_direction.casefold():
                    continue
                aliases = {"香港": "hong kong", "hongkong": "hong kong", "hk": "hong kong"}
                requested_location = (request.location or "").strip().casefold()
                actual_location = str(job["location"]).strip().casefold()
                if not request.location_unrestricted and aliases.get(
                    actual_location, actual_location
                ) != aliases.get(requested_location, requested_location):
                    continue
                if (
                    not request.employment_type_unrestricted
                    and job.get("employment_type") != request.employment_type
                ):
                    continue
                selected.append(
                    RawJob.model_validate(
                        {
                            "source": "synthetic-replay",
                            "source_url": job["source_url"],
                            "source_job_id": job["job_id"],
                            "fetched_at": job["fetched_at"],
                            "title": job["title"],
                            "company": job["company"],
                            "location": job["location"],
                            "salary": job.get("salary"),
                            "target_direction": request.target_direction,
                            "description": job["description"],
                            "posted_at": job.get("posted_at"),
                            "expiry_at": job.get("expiry_at"),
                            "employment_type": job.get("employment_type"),
                            "raw_payload": {
                                "freshness_status": job["freshness_status"],
                                "employment_type": job.get("employment_type"),
                                "description_is_excerpt": job.get("description_is_excerpt", False),
                            },
                        }
                    )
                )
                if len(selected) == 10:
                    break
            result.raw_jobs.extend(selected)
            result.outcomes.append(
                SourceOutcome(
                    request_index=index,
                    target_direction=request.target_direction,
                    source="synthetic-replay",
                    returned_count=len(selected),
                    candidate_count=len(selected),
                    status="ok" if selected else "empty",
                )
            )
        return result
