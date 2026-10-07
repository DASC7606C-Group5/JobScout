"""Explicit synthetic demo mode, never a fallback for live services."""

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from jobscout.schemas.profile import LocationRef
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.models import RawJob, SearchResult, SourceOutcome
from jobscout.services.llm_service import ToolCall, ToolTurn
from jobscout.services.location_service import CatalogEntry, LocationCatalog

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


@lru_cache(maxsize=1)
def replay_catalog() -> LocationCatalog:
    """Offline synthetic geography for the explicitly selected replay mode."""
    cities = [
        ("530", "北京", "Beijing"),
        ("538", "上海", "Shanghai"),
        ("763", "广州", "Guangzhou"),
        ("765", "深圳", "Shenzhen"),
        ("653", "杭州", "Hangzhou"),
        ("801", "成都", "Chengdu"),
        ("736", "武汉", "Wuhan"),
    ]
    return LocationCatalog(
        entries=[
            CatalogEntry(
                LocationRef(id="hk", name="Hong Kong", region="hk", level="country"),
                {"Hong Kong", "hongkong", "hk", "香港"},
                "synthetic-replay",
            ),
            CatalogEntry(
                LocationRef(id="cn:489", name="Mainland China", region="cn", level="country"),
                {"Mainland China", "China", "中国", "中國", "全国", "cn"},
                "synthetic-replay",
            ),
            *(
                CatalogEntry(
                    LocationRef(
                        id=f"cn:{code}",
                        name=name,
                        region="cn",
                        level="city",
                        parent_id="cn:489",
                        ancestor_ids=["cn:489"],
                        source_codes={"zhaopin": code},
                    ),
                    {name, english},
                    "synthetic-replay",
                )
                for code, name, english in cities
            ),
        ]
    )


def replay_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    locations: dict[str, Any] = {
        "included": [],
        "excluded": [],
        "unrestricted": bool(payload.get("location_unrestricted")),
    }
    employment: dict[str, Any] = {
        "included": [],
        "excluded": [],
        "unrestricted": bool(payload.get("employment_type_unrestricted")),
    }
    unrestricted = {
        "unrestricted",
        "any",
        "anywhere",
        "any location",
        "any employment type",
        "no preference",
        "不限",
    }
    employment_names = {
        "全职": "full-time",
        "实习": "internship",
        "兼职": "part-time",
        "合同": "contract",
        "自由职业": "freelance",
        "full time": "full-time",
        "part time": "part-time",
        "intern": "internship",
    }
    for raw, target in (
        (payload.get("location"), locations),
        (payload.get("employment_type"), employment),
    ):
        if not raw:
            continue
        if str(raw).strip().casefold() in unrestricted:
            target["unrestricted"] = True
            continue
        for part in re.split(r"[,，;/]|\s+(?:or|and)\s+", str(raw)):
            value = part.strip()
            if not value:
                continue
            if target is employment:
                canonical = employment_names.get(value.casefold(), value.casefold())
                if canonical in {"full-time", "part-time", "internship", "contract", "freelance"}:
                    target["included"].append(canonical)
            else:
                target["included"].append(value)
    work_mode = payload.get("work_mode")
    # Replay accepts only explicit UI enum values; live interpretation uses the model.
    return {
        "locations": locations,
        "employment": employment,
        "work_modes": [work_mode] if work_mode in {"remote", "hybrid", "onsite"} else [],
        "work_mode_uncertain": bool(work_mode) and work_mode not in {"remote", "hybrid", "onsite"},
    }


class ReplayProvider:
    model = "synthetic-replay-not-a-live-model"

    @property
    def location_catalog(self) -> LocationCatalog:
        return replay_catalog()

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        """Scripted observation policy for demos; never presented as a real-model result."""
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Replay deadline exhausted")
        observation = json.loads(messages[-1]["content"])
        candidates = [
            row["job_id"] for row in observation["candidates"] if row["analysis_attempts"] == 0
        ]
        arguments: dict[str, Any]
        if observation["matched_count"] >= observation["result_limit"]:
            name, arguments = "finish_search", {"reason": "target_reached"}
        elif candidates and observation["remaining_candidates"]:
            name, arguments = "assess_candidates", {"job_ids": candidates[:10]}
        else:
            remaining = observation["unexhausted_pairs"]
            if remaining:
                next_query = remaining[0]
                keywords = next_query.get("keywords", [next_query["direction"]])
                if next_query["next_action"] == "rephrase":
                    # Synthetic fixture policy, not a production language interpreter.
                    keywords = [f"{next_query['direction']} jobs"]
                name, arguments = (
                    "search_jobs",
                    {
                        "direction": next_query["direction"],
                        "source": next_query["source"],
                        "keywords": keywords,
                        "page": next_query["next_page"],
                    },
                )
            else:
                name, arguments = (
                    "finish_search",
                    {
                        "reason": "target_reached"
                        if observation["matched_count"] >= observation["result_limit"]
                        else "source_exhausted"
                    },
                )
        return ToolTurn(
            calls=[ToolCall(id=f"replay-{len(messages)}", name=name, arguments=arguments)]
        )

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
        elif name == "PreferenceMeaning":
            output = replay_preferences(payload)
        elif payload.get("task") == "jd_analysis":
            output = {"jobs": []}
            for job in payload["jobs"]:
                metadata = next(
                    (
                        document
                        for document in job["documents"]
                        if document["document_id"].endswith(":metadata")
                    ),
                    None,
                )
                facts = (metadata["text"].splitlines() + ["", "", ""]) if metadata else ["", "", ""]

                def citation(value: str, document: Any = metadata) -> list[dict[str, str]]:
                    return (
                        [{"document_id": document["document_id"], "excerpt": value}]
                        if document and value and value in document["text"]
                        else []
                    )

                title, location, employment = facts[:3]
                output["jobs"].append(
                    {
                        "job_id": job["job_id"],
                        "locations": [{"query": location, "source_quotes": citation(location)}]
                        if location
                        else [],
                        "employment": [{"value": employment, "source_quotes": citation(employment)}]
                        if employment
                        in {"full-time", "part-time", "internship", "contract", "freelance"}
                        else [],
                        "direction": "match" if title else "unknown",
                        "direction_quotes": citation(title),
                    }
                )
            for row, job in zip(output["jobs"], payload["jobs"], strict=True):
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
                row["requirements"] = requirements
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
                    "target_directions": "Choose job interests.",
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
            # Replay has no language model; confirmation uses the explicit UI action.
            output = {"intent": "answer", "changes": []}
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
        elif payload.get("task") == "matching":
            output = {"jobs": []}
            documents = payload["profile_documents"]
            skills = {
                fact["text"].casefold()
                for fact in payload["profile_facts"].values()
                if fact["field"] == "skills"
            }
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
                            "profile_fact_ids": [
                                identity
                                for identity, fact in payload["profile_facts"].items()
                                if fact["field"] == "skills"
                                and fact["text"].casefold() == text.casefold()
                            ]
                            if strong
                            else [],
                        }
                    )
                    suggestions.append(
                        {
                            "requirement_id": requirement["requirement_id"],
                            "suggestion": f"Prepare a small example demonstrating {text} and explain your approach.",
                        }
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
