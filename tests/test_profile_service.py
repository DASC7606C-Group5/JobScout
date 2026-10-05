"""Input-contract validation shared by AI extraction and source documents."""

import pytest

from jobscout.services.profile_service import (
    InputFormatError,
    dedupe,
    parse_profile_input,
    split_list_text,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"description": 42},
        {"resume": []},
        {"resume": {"text": 42}},
        {"target_directions": 42},
        {"target_directions": ["Data Analyst", 42]},
        {"preferences": []},
        {"preferences": {"unknown": "value"}},
    ],
)
def test_parse_profile_input_rejects_invalid_contract_values(payload: dict[str, object]) -> None:
    with pytest.raises(InputFormatError):
        parse_profile_input(payload)


def test_parse_profile_input_keeps_complete_unstructured_text() -> None:
    description = "Career story\nI use an unfamiliar tool and want to learn Python."
    resume = "My achievements\nBuilt a product using Bun and ClickHouse."
    parsed = parse_profile_input(
        {"description": f"  {description}  ", "resume": {"name": "cv.pdf", "text": resume}}
    )
    assert parsed.description == description
    assert parsed.resume == {"name": "cv.pdf", "text": resume}


def test_parse_profile_input_accepts_plain_text_resume() -> None:
    parsed = parse_profile_input({"resume": "Skills\nPython\n"})
    assert parsed.resume == {"name": "resume.txt", "text": "Skills\nPython"}


@pytest.mark.parametrize("resume", [None, "  ", {"name": "cv.txt", "text": "\n"}])
def test_parse_profile_input_drops_empty_resume(resume: object) -> None:
    assert parse_profile_input({"resume": resume}).resume is None


def test_parse_profile_input_drops_blank_directions_and_duplicates() -> None:
    parsed = parse_profile_input({"target_directions": ["Data Analyst", " ", "data analyst"]})
    assert parsed.target_directions == ["Data Analyst"]


def test_parse_profile_input_accepts_explicit_delimited_directions() -> None:
    parsed = parse_profile_input({"target_directions": "Data Analyst, Backend Engineer"})
    assert parsed.target_directions == ["Data Analyst", "Backend Engineer"]


def test_explicit_list_normalization_preserves_unknown_multiword_values() -> None:
    assert split_list_text("Bun; Looker Studio，stakeholder management / Bun") == [
        "Bun",
        "Looker Studio",
        "stakeholder management",
    ]
    assert dedupe([" Bun ", "bun", "", "ClickHouse"]) == ["Bun", "ClickHouse"]
