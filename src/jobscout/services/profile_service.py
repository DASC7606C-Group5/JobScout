"""Validate profile inputs and normalize explicit lists.

ConversationService asks the model to read the resume and description.
These helpers check field types without guessing facts from resume text.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypedDict

from pydantic import ValidationError

from jobscout.schemas.profile import RawProfilePreferences


class InputFormatError(ValueError):
    """Raised when user input does not follow the agreed input format."""


class ResumeFile(TypedDict):
    """Resume name and extracted text sent by the frontend."""

    name: str
    text: str


@dataclass(frozen=True)
class ProfileInput:
    """Normalized user input consumed by profile extraction."""

    description: str
    resume: ResumeFile | None
    target_directions: list[str]
    preferences: RawProfilePreferences


def parse_profile_input(input_data: Mapping[str, object]) -> ProfileInput:
    """Validate and normalize standardized user input.

    Args:
        input_data: Raw ``input_data`` value taken from ``AgentState``.

    Returns:
        Normalized description, optional resume, target directions, and preferences.

    Raises:
        InputFormatError: If a supplied value does not match the agreed input format.
    """
    return ProfileInput(
        description=_parse_description(input_data.get("description")),
        resume=_parse_resume(input_data.get("resume")),
        target_directions=_parse_directions(input_data.get("target_directions")),
        preferences=_parse_preferences(input_data.get("preferences")),
    )


def _parse_description(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raise InputFormatError("description must be a string.")


def _parse_resume(value: object) -> ResumeFile | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if set(value) != {"name", "text"}:
            raise InputFormatError("resume must contain name and text.")
        raw_name = value["name"]
        if not isinstance(raw_name, str):
            raise InputFormatError("resume.name must be a string.")
        raw_text = value.get("text")
        if not isinstance(raw_text, str):
            raise InputFormatError("resume.text must be a string.")
        if not raw_text.strip():
            return None
        return ResumeFile(name=raw_name.strip(), text=raw_text.strip())
    raise InputFormatError("resume must be an object with name and text, or null.")


def _parse_directions(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
        if len(items) != len(value):
            raise InputFormatError("target_directions must only contain strings.")
        return dedupe(item.strip() for item in items if item.strip())
    raise InputFormatError("target_directions must be a list of strings.")


def _parse_preferences(value: object) -> RawProfilePreferences:
    if value is None:
        return RawProfilePreferences()
    if isinstance(value, dict):
        try:
            return RawProfilePreferences.model_validate(value)
        except ValidationError as error:
            raise InputFormatError(
                "preferences does not match the agreed preference fields."
            ) from error
    raise InputFormatError("preferences must be an object or null.")


def dedupe(items: Iterable[str]) -> list[str]:
    """De-duplicate strings case-insensitively while preserving first-seen order.

    Args:
        items: Raw string values, possibly blank or repeated.

    Returns:
        Trimmed, non-blank values with case-insensitive duplicates removed.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        stripped = item.strip()
        key = stripped.casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(stripped)
    return result


def split_list_text(text: str) -> list[str]:
    """Split a free-text answer into list items.

    Args:
        text: Explicit list items separated by newlines. Punctuation remains part of each item.

    Returns:
        Non-blank, de-duplicated items in first-seen order.
    """
    return dedupe(part for part in text.splitlines() if part.strip())
