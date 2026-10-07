"""Model-assisted conversation with server-controlled search preferences."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import QuestionOption
from jobscout.schemas.job import SourceDocument
from jobscout.schemas.profile import (
    EmploymentCondition,
    LocationCondition,
    ProfileSource,
    RawProfilePreferences,
    SearchOptions,
    UserProfile,
)
from jobscout.schemas.search import ClarificationMessage
from jobscout.services.condition_service import ConditionService
from jobscout.services.llm_service import LLMProvider, ModelServiceError
from jobscout.services.profile_service import dedupe, parse_profile_input, split_list_text
from jobscout.services.prompts import (
    ANSWER_INTERPRETATION_PROMPT,
    CLARIFICATION_PROMPT,
    PROFILE_EXTRACTION_PROMPT,
)

BACKGROUND_FIELDS = ("education", "skills", "internships", "projects")
REQUIRED_FIELDS = ("target_directions", "preferences.location", "preferences.employment_type")
_REQUIRED_QUESTIONS = {
    "target_directions": "Choose specific job interests.",
    "preferences.location": "Specify your work location (Hong Kong, mainland China, or any location).",
    "preferences.employment_type": "Specify your employment type (full-time, internship, part-time, contract, freelance, or no preference).",
}
OPTIONAL_FIELDS = (
    *BACKGROUND_FIELDS,
    "preferences.salary_range",
    "preferences.work_mode",
    "preferences.industry",
)
EDITABLE_FIELDS = (
    *REQUIRED_FIELDS,
    *OPTIONAL_FIELDS,
    "preferences.location_unrestricted",
    "preferences.employment_type_unrestricted",
)


class ConversationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileExtraction(ConversationSchema):
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    target_directions: list[str] = Field(default_factory=list)
    preferences: RawProfilePreferences = Field(default_factory=RawProfilePreferences)
    conflicts: list[str] = Field(default_factory=list)


class QuestionDraft(ConversationSchema):
    field: str
    question: str
    reason: str
    control_type: Literal["single_choice", "multiple_choice", "text"] = "text"
    options: list[QuestionOption] = Field(default_factory=list)


class QuestionGeneration(ConversationSchema):
    questions: list[QuestionDraft] = Field(default_factory=list, max_length=3)


class ProfileChange(ConversationSchema):
    field: str
    value: str | list[str] | bool | None
    mode: Literal["replace", "merge"] = "replace"


class AnswerInterpretation(ConversationSchema):
    intent: Literal["answer", "confirm_search", "defer_search", "question"]
    changes: list[ProfileChange] = Field(default_factory=list)


def _messages(instruction: str, data: object) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": instruction,
        },
        {"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)},
    ]


def _strings(value: str | list[str] | bool | None) -> list[str]:
    if isinstance(value, list):
        return dedupe(item.strip() for item in value if item.strip())
    return split_list_text(value) if isinstance(value, str) else []


def apply_changes(profile: UserProfile, changes: Sequence[ProfileChange]) -> UserProfile:
    data = profile.model_dump()
    changed: list[str] = []
    for change in changes:
        field, value = change.field, change.value
        if field not in EDITABLE_FIELDS:
            raise ValueError("Unknown profile field.")
        if field in (*BACKGROUND_FIELDS, "target_directions"):
            items = _strings(value)
            if isinstance(value, bool):
                raise ValueError("List field requires text or a list.")
            data[field] = dedupe([*data[field], *items]) if change.mode == "merge" else items
        else:
            name = field.removeprefix("preferences.")
            preferences = data["preferences"]
            if name.endswith("_unrestricted"):
                if not isinstance(value, bool):
                    raise ValueError("Unrestricted flag must be a boolean.")
                preferences[name] = value
                if value:
                    primary = name.removesuffix("_unrestricted")
                    preferences[primary] = None
                    changed.append(f"preferences.{primary}")
            else:
                if isinstance(value, (bool, list)):
                    raise ValueError("Preference requires a text value.")
                text = value.strip() if isinstance(value, str) else None
                if name in {"location", "employment_type"}:
                    preferences[name + "_unrestricted"] = False
                    preferences["locations" if name == "location" else "employment"] = (
                        LocationCondition() if name == "location" else EmploymentCondition()
                    ).model_dump()
                preferences[name] = text or None
        changed.append(field)
    data["conflicts"] = [field for field in data["conflicts"] if field not in changed]
    data["confirmed_fields"] = dedupe([*data["confirmed_fields"], *changed])
    return UserProfile.model_validate(data)


def missing_fields(profile: UserProfile) -> list[str]:
    result: list[str] = []
    if not profile.target_directions or not all(d.strip() for d in profile.target_directions):
        result.append("target_directions")
    preferences = profile.preferences
    if not preferences.locations.unrestricted and not preferences.locations.included:
        result.append("preferences.location")
    if any(
        ref.resolution != "resolved"
        for ref in [*preferences.locations.included, *preferences.locations.excluded]
    ):
        result.append("preferences.location")
    if not preferences.employment.unrestricted and not preferences.employment.included:
        result.append("preferences.employment_type")
    return dedupe([*result, *profile.conflicts])


def profile_documents(input_data: Mapping[str, object], session_id: str) -> list[SourceDocument]:
    parsed = parse_profile_input(input_data)
    texts = [
        ("description", parsed.description),
        ("resume", parsed.resume["text"] if parsed.resume else ""),
    ]
    return [
        SourceDocument(
            document_id=f"profile:{session_id}:{kind}",
            source="user",
            source_url="",
            text=text,
            fetched_at=datetime.now(UTC),
        )
        for kind, text in texts
        if text
    ]


class ConversationService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.conditions = ConditionService(provider)

    async def resolve_preferences(
        self, profile: UserProfile, *, deadline: float | None = None
    ) -> UserProfile:
        return await self.conditions.resolve(profile, deadline=deadline)

    async def extract(self, input_data: Mapping[str, object], session_id: str) -> UserProfile:
        parsed = parse_profile_input(input_data)
        if not parsed.description and parsed.resume is None:
            raise ValueError("A resume or personal description is required.")
        extracted = await self.provider.structured(
            ProfileExtraction,
            _messages(
                PROFILE_EXTRACTION_PROMPT,
                {"description": parsed.description, "resume": parsed.resume},
            ),
        )
        extracted = ProfileExtraction.model_validate(extracted.model_dump())
        profile = UserProfile(
            profile_id=session_id,
            source=ProfileSource(
                resume=parsed.resume is not None, description=bool(parsed.description)
            ),
            **extracted.model_dump(),
            search_options=SearchOptions.model_validate(input_data.get("search_options") or {}),
        )
        profile.conflicts = [field for field in profile.conflicts if field in EDITABLE_FIELDS]
        updates: list[ProfileChange] = []
        if parsed.target_directions:
            updates.append(ProfileChange(field="target_directions", value=parsed.target_directions))
        for key, value in parsed.preferences.model_dump().items():
            if value is not None and value is not False:
                updates.append(ProfileChange(field=f"preferences.{key}", value=value))
        profile = apply_changes(profile, updates)
        return await self.resolve_preferences(profile)

    async def questions(
        self, profile: UserProfile, required: list[str], suppressed: list[str], turn: int
    ) -> list[ClarificationMessage]:
        allowed = required or [field for field in OPTIONAL_FIELDS if field not in suppressed]
        if not allowed:
            return []
        draft = await self.provider.structured(
            QuestionGeneration,
            _messages(
                CLARIFICATION_PROMPT,
                {
                    "profile": profile.model_dump(),
                    "allowed_fields": allowed,
                    "required_fields": required,
                    "suppressed_fields": suppressed,
                },
            ),
        )
        draft = QuestionGeneration.model_validate(draft.model_dump())
        result: list[ClarificationMessage] = []
        seen: set[str] = set()
        for item in draft.questions:
            if item.field not in allowed or item.field in seen or not item.question.strip():
                continue
            seen.add(item.field)
            options = item.options
            if len({option.id for option in options}) != len(options):
                raise ModelServiceError("model_output")
            result.append(
                ClarificationMessage(
                    **item.model_dump(exclude={"control_type"}),
                    control_type=item.control_type if options else "text",
                    required=item.field in required,
                    question_id=f"q{turn}:{item.field}",
                )
            )
        for field in required:
            if field not in seen and len(result) < 3:
                result.append(
                    ClarificationMessage(
                        field=field,
                        question=_REQUIRED_QUESTIONS.get(
                            field, "Please provide this job search preference."
                        ),
                        reason="This must be confirmed before we search.",
                        question_id=f"q{turn}:{field}",
                    )
                )
        return result[:3]

    async def interpret(
        self, profile: UserProfile, message: str, *, confirmation_ready: bool = False
    ) -> AnswerInterpretation:
        if not message.strip():
            return AnswerInterpretation(intent="answer")
        result = await self.provider.structured(
            AnswerInterpretation,
            _messages(
                ANSWER_INTERPRETATION_PROMPT,
                {
                    "profile": profile.model_dump(),
                    "message": message,
                    "editable_fields": EDITABLE_FIELDS,
                    "confirmation_ready": confirmation_ready,
                },
            ),
        )
        result = AnswerInterpretation.model_validate(result.model_dump())
        if any(change.field not in EDITABLE_FIELDS for change in result.changes):
            raise ModelServiceError("model_output")
        return result
