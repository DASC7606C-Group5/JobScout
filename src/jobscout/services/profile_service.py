"""Validate profile inputs and normalize explicit lists.

ConversationService owns semantic extraction through its structured AI provider.
These helpers validate the input contract without guessing facts from CV text.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypedDict

from pydantic import ValidationError

from jobscout.schemas.profile import ProfilePreferences


class InputFormatError(ValueError):
    """Raised when user input does not follow the agreed input format."""


class ResumeFile(TypedDict):
    """Resume payload as produced by the frontend input contract."""

    name: str
    text: str


@dataclass(frozen=True)
class ProfileInput:
    """Normalized user input consumed by profile extraction."""

    description: str
    resume: ResumeFile | None
    target_directions: list[str]
    preferences: ProfilePreferences


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
    if isinstance(value, str):
        text = value.strip()
        return ResumeFile(name="resume.txt", text=text) if text else None
    if isinstance(value, dict):
        raw_text = value.get("text")
        if not isinstance(raw_text, str):
            raise InputFormatError("resume.text must be a string.")
        if not raw_text.strip():
            return None
        raw_name = value.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else "resume.txt"
        return ResumeFile(name=name, text=raw_text.strip())
    raise InputFormatError("resume must be an object with name and text, or null.")


def _parse_directions(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return split_list_text(value)
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
        if len(items) != len(value):
            raise InputFormatError("target_directions must only contain strings.")
        return dedupe(item.strip() for item in items if item.strip())
    raise InputFormatError("target_directions must be a list of strings.")


def _parse_preferences(value: object) -> ProfilePreferences:
    if value is None:
        return ProfilePreferences()
    if isinstance(value, ProfilePreferences):
        return value.model_copy()
    if isinstance(value, dict):
        try:
            return ProfilePreferences.model_validate(value)
        except ValidationError as error:
            raise InputFormatError(
                "preferences does not match the agreed preference fields."
            ) from error
    raise InputFormatError("preferences must be an object or null.")


_LIST_SEPARATOR = re.compile(r"[,，、;；/|]")


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
        text: Answer text separated by commas, semicolons, slashes, or pipes.

    Returns:
        Non-blank, de-duplicated items in first-seen order.
    """
    return dedupe(part for part in _LIST_SEPARATOR.split(text) if part.strip())
