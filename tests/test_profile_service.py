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
        {"resume": "Skills\nPython\n"},
        {"resume": {"text": "Python"}},
        {"resume": {"name": 42, "text": "Python"}},
        {"resume": {"name": "cv.txt", "text": 42}},
        {"resume": {"name": "cv.txt", "text": "Python", "unknown": "value"}},
        {"target_directions": 42},
        {"target_directions": "Data Analyst, Backend Engineer"},
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


@pytest.mark.parametrize("resume", [None, {"name": "cv.txt", "text": "\n"}])
def test_parse_profile_input_drops_empty_resume(resume: object) -> None:
    assert parse_profile_input({"resume": resume}).resume is None


def test_parse_profile_input_drops_blank_directions_and_duplicates() -> None:
    parsed = parse_profile_input({"target_directions": ["Data Analyst", " ", "data analyst"]})
    assert parsed.target_directions == ["Data Analyst"]


def test_explicit_list_normalization_preserves_unknown_multiword_values() -> None:
    assert split_list_text("Bun\nLooker Studio\nstakeholder management\nBun") == [
        "Bun",
        "Looker Studio",
        "stakeholder management",
    ]
    assert dedupe([" Bun ", "bun", "", "ClickHouse"]) == ["Bun", "ClickHouse"]


def test_list_normalization_preserves_punctuation_inside_skills_and_roles() -> None:
    assert split_list_text(
        "CI/CD\nUI/UX Designer\nTCP/IP\nA | B\nC++\nBSc, Computer Science\n数据分析，业务研究"
    ) == [
        "CI/CD",
        "UI/UX Designer",
        "TCP/IP",
        "A | B",
        "C++",
        "BSc, Computer Science",
        "数据分析，业务研究",
    ]
