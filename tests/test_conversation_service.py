"""AI extraction routing and contract checks with an injected model provider."""

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

from jobscout.services.conversation_service import ConversationService, ProfileExtraction
from jobscout.services.llm_service import ModelServiceError


class ExtractionProvider:
    def __init__(self, output: dict[str, Any], *, error: str | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[type[BaseModel], list[dict[str, str]]]] = []

    async def structured[T: BaseModel](
        self,
        schema: type[T],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> T:
        self.calls.append((schema, messages))
        if self.error:
            raise ModelServiceError(self.error)
        return schema.model_validate(self.output if schema is ProfileExtraction else {})


def test_extract_sends_complete_sources_and_keeps_open_ended_model_facts() -> None:
    description = "I now use Bun and ClickHouse. I do not know Python."
    resume_text = (
        "My journey\nStudied at Example College.\nBuilt an analytics product.\n"
        "Worked with product stakeholders using stakeholder management skills."
    )
    output = {
        "education": ["Studied at Example College."],
        "skills": ["Bun", "ClickHouse", "Stakeholder management"],
        "internships": ["Worked with product stakeholders."],
        "projects": ["Built an analytics product."],
    }
    provider = ExtractionProvider(output)
    profile = asyncio.run(
        ConversationService(provider).extract(
            {"description": description, "resume": {"name": "cv.pdf", "text": resume_text}},
            "session-1",
        )
    )
    assert profile.profile_id == "session-1"
    assert profile.source.description and profile.source.resume
    for field, values in output.items():
        assert getattr(profile, field) == values
    assert profile.target_directions == []
    assert profile.preferences.location is None
    assert len(provider.calls) == 1
    schema, messages = provider.calls[0]
    assert schema is ProfileExtraction
    assert json.loads(messages[-1]["content"]) == {
        "description": description,
        "resume": {"name": "cv.pdf", "text": resume_text},
    }


def test_explicit_form_choices_override_model_preferences_and_conflicts() -> None:
    provider = ExtractionProvider(
        {
            "target_directions": ["Accountant"],
            "preferences": {"location": "Shanghai", "employment_type": "full-time"},
            "conflicts": ["preferences.location", "preferences.employment_type", "profile_id"],
        }
    )
    profile = asyncio.run(
        ConversationService(provider).extract(
            {
                "description": "My background.",
                "target_directions": ["Data Analyst", "Backend Engineer"],
                "preferences": {"location": "Hong Kong", "employment_type": "internship"},
            },
            "session-2",
        )
    )
    assert profile.target_directions == ["Data Analyst", "Backend Engineer"]
    assert profile.preferences.location == "Hong Kong"
    assert profile.preferences.employment_type == "internship"
    assert profile.conflicts == []


def test_complementary_model_skills_remain_without_a_local_conflict_rule() -> None:
    provider = ExtractionProvider({"skills": ["Python", "SQL", "Java", "Golang"]})
    profile = asyncio.run(
        ConversationService(provider).extract(
            {
                "description": "I also know Java and Golang.",
                "resume": {"name": "cv.txt", "text": "I know Python and SQL."},
            },
            "session-3",
        )
    )
    assert profile.skills == ["Python", "SQL", "Java", "Golang"]
    assert profile.conflicts == []


@pytest.mark.parametrize("code", ["model_auth", "model_output", "model_timeout"])
def test_model_failure_does_not_fall_back_to_keyword_extraction(code: str) -> None:
    provider = ExtractionProvider({}, error=code)
    with pytest.raises(ModelServiceError) as raised:
        asyncio.run(
            ConversationService(provider).extract(
                {"description": "Skills\nPython, SQL"}, "failed-session"
            )
        )
    assert raised.value.code == code


def test_empty_materials_are_rejected_before_a_model_call() -> None:
    provider = ExtractionProvider({})
    with pytest.raises(ValueError, match="resume or personal description"):
        asyncio.run(ConversationService(provider).extract({}, "empty-session"))
    assert provider.calls == []
