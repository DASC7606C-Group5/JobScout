"""Scripted model behavior with optional, explicitly injected replay samples."""

import asyncio
import json
import re
from typing import Any

from pydantic import BaseModel

from jobscout.replay.dataset import ReplayDataset
from jobscout.replay.locations import replay_catalog, replay_preferences
from jobscout.services.llm_service import ToolCall, ToolTurn
from jobscout.services.location_service import LocationCatalog


def _payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    return dict(json.loads(messages[-1]["content"]))


class SyntheticProvider:
    model = "synthetic-replay-not-a-live-model"

    def profile_background(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {}

    def job_requirements(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

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
        if observation["useful_count"] >= observation["result_limit"]:
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
                        if observation["useful_count"] >= observation["result_limit"]
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
        if name == "ResultInterpretation":
            request = payload["request"]
            message = request.get("message", "")
            answers = payload.get("answers", [])
            text = " ".join([message, *(str(answer["value"]) for answer in answers)])
            output: dict[str, Any] = {
                "reply": "The supplied job details do not establish any additional information.",
                "search_requested": request["action"] == "find_similar"
                or any(
                    word in text.casefold()
                    for word in ("find more", "search more", "补搜", "更多岗位")
                ),
            }
            if (
                message.casefold()
                in {"这种不喜欢", "i don't like this kind", "this kind is not for me"}
                and not answers
            ):
                output["questions"] = [
                    {
                        "field": "result_preference",
                        "question": "Which responsibilities or working conditions do you want to exclude?",
                        "reason": "A single reaction does not identify a category.",
                    }
                ]
                output["reply"] = "Please clarify what you want to exclude."
            elif any(word in text.casefold() for word in ("sales", "销售")):
                rule = next(
                    (
                        rule
                        for rule in payload["result_preferences"]["exclusions"]
                        if any(word in rule["description"].casefold() for word in ("sales", "销售"))
                    ),
                    None,
                )
                if (
                    any(word in text.casefold() for word in ("allow sales", "cancel", "取消"))
                    and rule
                ):
                    output["remove_exclusion_ids"] = [rule["exclusion_id"]]
                elif any(
                    word in text.casefold()
                    for word in ("exclude", "don't want", "不想", "排除", "不喜欢")
                ):
                    output["exclusions"] = [
                        {"description": str(answers[-1]["value"]) if answers else message}
                    ]
                    if payload.get("feedback"):
                        output["feedback_reason"] = (
                            str(answers[-1]["value"]) if answers else message
                        )
                    output["reply"] = (
                        "Sales roles will be hidden when their listed duties establish a match."
                    )
            for feature in ("Python", "remote"):
                if feature.casefold() in text.casefold() and any(
                    word in text.casefold() for word in ("like", "prefer", "喜欢")
                ):
                    output.setdefault("preferred_features", []).append(
                        {"feature": feature, "source_text": message}
                    )
        elif name == "ExclusionMatches":
            output = {"matches": []}
            jobs = {job["job_id"]: job["content"] for job in payload["jobs"]}
            rules = {rule["exclusion_id"]: rule["description"] for rule in payload["exclusions"]}
            for pair in payload["pairs"]:
                content = jobs[pair["job_id"]]
                description = rules[pair["exclusion_id"]]
                quote = next((word for word in ("Sales", "sales", "销售") if word in content), None)
                known_rule = any(word in description.casefold() for word in ("sales", "销售"))
                output["matches"].append(
                    {
                        **pair,
                        "decision": "matches" if quote and known_rule else "unknown",
                        "quotes": [quote] if quote and known_rule else [],
                    }
                )
        elif name == "ProfileExtraction":
            output = self.profile_background(payload)
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
                row["requirements"] = self.job_requirements(job["documents"])
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
            documents = payload["profile_quotes"]
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
                        (doc_id for doc_id, content in documents.items() if text in content),
                        None,
                    )
                    strong = text.casefold() in skills and ref is not None
                    matches.append(
                        {
                            "requirement_id": requirement["requirement_id"],
                            "level": "strong" if strong else "not_documented",
                            "profile_quote_ids": [ref] if strong else [],
                            "explanation": f"The supplied background {'documents' if strong else 'does not mention'} {text}.",
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
                        f"Prepare a small example demonstrating {text} and explain your approach."
                    )
                output["jobs"].append(
                    {
                        "job_id": job["job_id"],
                        "recommendation_fit": "possible",
                        "recommendation_reason": "Your background offers experience relevant to this role.",
                        "matches": matches,
                        "preparation_suggestions": suggestions[:2],
                    }
                )
        else:
            raise ValueError("Unsupported replay schema; no live fallback")
        result = output["jobs"][0] if payload.get("task") == "matching" else output
        if schema.__name__ == "SummaryReviewResponse":
            result.pop("preparation_suggestions", None)
        return schema.model_validate(result)


class ReplayProvider(SyntheticProvider):
    def __init__(self, dataset: ReplayDataset) -> None:
        self.dataset = dataset

    def profile_background(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Replay background facts for an exact sample; never parse arbitrary CVs."""
        description = payload.get("description", "").strip()
        resume_text = (payload.get("resume") or {}).get("text", "").strip()
        for case in self.dataset.profiles:
            sample = case["input"]
            resume = sample["resume"]
            if (
                sample["description"].strip() == description
                and (resume["text"].strip() if resume else "") == resume_text
            ):
                return dict(case["background"])
        return {}

    def job_requirements(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        requirements: list[dict[str, Any]] = []
        for sample in self.dataset.jobs:
            if not any(
                document["source_url"] == sample["job"]["source_url"] for document in documents
            ):
                continue
            for requirement in sample["requirements"]:
                source_quotes = [
                    {"document_id": document["document_id"], "excerpt": ref["excerpt"]}
                    for ref in requirement["references"]
                    for document in documents
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
        return requirements
