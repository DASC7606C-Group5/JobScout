"""Structured understanding for conversations about retained search results."""

import json
from typing import Any, Literal

from pydantic import Field

from jobscout.schemas.feedback import FeedbackModel
from jobscout.services.conversation_service import ProfileChange, QuestionDraft
from jobscout.services.llm_service import LLMProvider, ModelServiceError
from jobscout.services.prompts import RESULT_CONVERSATION_PROMPT


class ResultProfileChange(ProfileChange):
    source_text: str


class PreferredFeature(FeedbackModel):
    feature: str
    source_text: str


class ResultQuestion(QuestionDraft):
    required_for_action: bool = True


class ExclusionDraft(FeedbackModel):
    description: str
    condition_field: Literal["semantic", "location", "employment_type", "work_mode"] = "semantic"


class ResultInterpretation(FeedbackModel):
    reply: str
    search_requested: bool = False
    questions: list[ResultQuestion] = Field(default_factory=list, max_length=3)
    profile_changes: list[ResultProfileChange] = Field(default_factory=list)
    preferred_features: list[PreferredFeature] = Field(default_factory=list)
    exclusions: list[ExclusionDraft] = Field(default_factory=list)
    remove_exclusion_ids: list[str] = Field(default_factory=list)
    feedback_reason: str | None = None


class ResultConversationService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def interpret(self, data: dict[str, Any], *, deadline: float) -> ResultInterpretation:
        result = await self.provider.structured(
            ResultInterpretation,
            [
                {"role": "system", "content": RESULT_CONVERSATION_PROMPT},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)},
            ],
            deadline=deadline,
        )
        texts = [
            data["request"].get("message", ""),
            data.get("answer_message", ""),
            *(
                label
                for answer in data.get("answers", [])
                for label in answer.get("selected_option_labels", [])
            ),
            *(
                value
                for answer in data.get("answers", [])
                for value in (
                    answer["value"] if isinstance(answer["value"], list) else [answer["value"]]
                )
            ),
        ]

        def supplied(text: str) -> bool:
            return bool(text.strip()) and any(text in original for original in texts)

        ids = {rule["exclusion_id"] for rule in data["result_preferences"]["exclusions"]}
        if (
            any(not supplied(rule.description) for rule in result.exclusions)
            or any(
                not supplied(feature.source_text) or not feature.feature.strip()
                for feature in result.preferred_features
            )
            or any(
                not supplied(change.source_text)
                or (
                    change.field != "target_directions"
                    and not change.field.startswith("preferences.")
                )
                for change in result.profile_changes
            )
            or not set(result.remove_exclusion_ids) <= ids
            or (
                result.feedback_reason is not None
                and (not data.get("feedback") or not supplied(result.feedback_reason))
            )
            or (
                result.questions
                and (
                    result.profile_changes
                    or result.exclusions
                    or result.remove_exclusion_ids
                    or result.preferred_features
                )
            )
        ):
            raise ModelServiceError("model_output")
        return result
