"""Tests for profile extraction, missing fields, conflicts, and clarification."""

from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from jobscout.graph.nodes.clarification import clarification_node
from jobscout.graph.nodes.profile import extract_profile_node, validate_profile_node
from jobscout.graph.routing import route_after_clarification, route_after_validation
from jobscout.graph.state import AgentState
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.search import ClarificationStatus
from jobscout.services.profile_service import (
    EMPLOYMENT_TYPE_UNRESTRICTED,
    InputFormatError,
    apply_answers,
    build_clarification_questions,
    build_profile,
    detect_conflicts,
    extract_background,
    parse_profile_input,
)

RESUME_TEXT = """\
Summary
Backend engineer focused on data platforms.

Education
BSc Computer Science, Example University

Skills
Python, SQL, Docker

Internships
Data Engineer Intern, Example Co

Projects
JobScout job pipeline
"""

DESCRIPTION_TEXT = "I build backend services with Python and want to move into data engineering."


def complete_input(**overrides: object) -> dict[str, object]:
    """Return a standardized ScoutInput shaped payload with all required data."""
    payload: dict[str, object] = {
        "description": DESCRIPTION_TEXT,
        "resume": {"name": "resume.txt", "text": RESUME_TEXT},
        "target_directions": ["data engineer", "backend engineer"],
        "preferences": {
            "location": "Hong Kong",
            "location_unrestricted": False,
            "employment_type": "full-time",
            "salary_range": None,
            "work_mode": "hybrid",
            "industry": "technology",
        },
    }
    payload.update(overrides)
    return payload


def missing_input() -> dict[str, object]:
    """Return a payload without resume, description, direction, location, or type."""
    return {
        "description": "",
        "resume": None,
        "target_directions": [],
        "preferences": {
            "location": None,
            "location_unrestricted": False,
            "employment_type": None,
        },
    }


def conflicting_input() -> dict[str, object]:
    """Return a complete payload whose resume and description share no skills."""
    return complete_input(
        description="Skills\nJava, Golang\n",
        resume={"name": "resume.txt", "text": "Skills\nPython, SQL\n"},
    )


def build_from_input(payload: dict[str, object], profile_id: str = "profile-1") -> UserProfile:
    """Run the deterministic profile pipeline over a standardized payload."""
    parsed = parse_profile_input(payload)
    return build_profile(
        profile_id,
        description=parsed.description,
        resume=parsed.resume,
        target_directions=parsed.target_directions,
        preferences=parsed.preferences,
    )


def make_state(**updates: object) -> AgentState:
    """Build a minimal AgentState for node level tests."""
    state: dict[str, object] = {"session_id": "session-1"}
    state.update(updates)
    return cast(AgentState, state)


def test_extract_background_parses_resume_sections() -> None:
    background = extract_background(RESUME_TEXT)

    assert background.education == ["BSc Computer Science, Example University"]
    assert background.skills == ["Python", "SQL", "Docker"]
    assert background.internships == ["Data Engineer Intern, Example Co"]
    assert background.projects == ["JobScout job pipeline"]


def test_extract_background_scans_free_text_for_known_skills() -> None:
    background = extract_background("I use Excel and pandas for weekly data analysis reports.")

    assert sorted(background.skills) == ["Data Analysis", "Excel", "pandas"]
    assert background.education == []


def test_extract_background_splits_space_separated_skills() -> None:
    background = extract_background("Skills\nPython SQL Docker\n")

    assert background.skills == ["Python", "SQL", "Docker"]


def test_extract_background_keeps_unknown_multiword_skills() -> None:
    background = extract_background("Skills\nTableau, Looker Studio\n")

    assert background.skills == ["Tableau", "Looker Studio"]


def test_extract_background_recognizes_skill_aliases() -> None:
    background = extract_background("I use Postgres, k8s and PowerBI.")

    assert sorted(background.skills) == ["Kubernetes", "PostgreSQL", "Power BI"]


def test_extract_background_reads_chinese_section_titles() -> None:
    text = "任职经历\nData Intern, Acme\n\n项目经验\nJobScout pipeline\n"

    background = extract_background(text)

    assert background.internships == ["Data Intern, Acme"]
    assert background.projects == ["JobScout pipeline"]


def test_extract_background_keeps_entries_after_a_colon_label() -> None:
    text = "工作经历\nAcme, Data Intern\nResponsibilities:\n- Built ETL pipelines\n"

    background = extract_background(text)

    assert background.internships == [
        "Acme, Data Intern",
        "Responsibilities:",
        "Built ETL pipelines",
    ]


def test_extract_background_orders_skills_by_first_appearance() -> None:
    background = extract_background("I use Python, then SQL, then Docker.")

    assert background.skills == ["Python", "SQL", "Docker"]


def test_build_profile_from_complete_input() -> None:
    profile = build_from_input(complete_input())

    assert profile.profile_id == "profile-1"
    assert profile.source.resume is True
    assert profile.source.description is True
    assert profile.target_directions == ["data engineer", "backend engineer"]
    assert profile.preferences.location == "Hong Kong"
    assert profile.preferences.employment_type == "full-time"
    assert profile.preferences.work_mode == "hybrid"
    assert "Python" in profile.skills
    assert profile.missing_required_fields == []
    assert profile.conflicts == []
    assert profile.confirmed_fields == []


def test_build_profile_reports_all_required_gaps() -> None:
    profile = build_from_input(missing_input())

    assert profile.source.resume is False
    assert profile.source.description is False
    assert profile.missing_required_fields == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert profile.conflicts == []


def test_unrestricted_location_is_not_a_required_gap() -> None:
    payload = missing_input()
    payload["target_directions"] = ["data analyst"]
    payload["preferences"] = {
        "location": None,
        "location_unrestricted": True,
        "employment_type": "internship",
    }

    profile = build_from_input(payload)

    assert profile.missing_required_fields == []
    assert profile.preferences.location_unrestricted is True


def test_disjoint_skills_are_complementary_not_a_conflict() -> None:
    resume_background = extract_background("Skills\nPython, SQL\n")
    description_background = extract_background("Skills\nJava, Golang\n")

    assert detect_conflicts(resume_background, description_background) == []

    profile = build_from_input(conflicting_input())

    assert profile.conflicts == []
    assert profile.missing_required_fields == []
    assert profile.skills == ["Python", "SQL", "Java", "Golang"]


def test_overlapping_skills_are_not_a_conflict() -> None:
    resume_background = extract_background("Skills\nPython, SQL\n")
    description_background = extract_background("Skills\nPython\n")

    assert detect_conflicts(resume_background, description_background) == []


def test_parse_profile_input_rejects_unstandardized_values() -> None:
    with pytest.raises(InputFormatError):
        parse_profile_input({"target_directions": 42})

    with pytest.raises(InputFormatError):
        parse_profile_input({"preferences": {"unknown": "value"}})


def test_parse_profile_input_accepts_plain_text_resume() -> None:
    parsed = parse_profile_input({"resume": "Skills\nPython\n"})

    resume = parsed.resume
    assert resume is not None
    assert resume["name"] == "resume.txt"
    assert resume["text"] == "Skills\nPython"


def test_parse_profile_input_drops_blank_directions_and_duplicates() -> None:
    parsed = parse_profile_input({"target_directions": ["Data Analyst", " ", "data analyst"]})

    assert parsed.target_directions == ["Data Analyst"]


def test_build_clarification_questions_covers_every_required_gap() -> None:
    questions = build_clarification_questions(build_from_input(missing_input()))

    assert [question.field for question in questions] == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert all(question.required for question in questions)
    assert all(question.status is ClarificationStatus.PENDING for question in questions)
    assert all(question.question and question.reason for question in questions)


def test_build_clarification_questions_asks_about_the_conflict() -> None:
    profile = build_from_input(conflicting_input()).model_copy(update={"conflicts": ["skills"]})
    questions = build_clarification_questions(profile)

    assert [question.field for question in questions] == ["skills"]
    assert questions[0].required is True


def test_build_clarification_questions_without_profile_asks_for_a_direction() -> None:
    questions = build_clarification_questions(None)

    assert [question.field for question in questions] == ["target_directions"]


def test_build_clarification_questions_uses_english_copy() -> None:
    questions = build_clarification_questions(build_from_input(missing_input()))

    assert questions[0].question == "What kind of roles are you looking for?"
    assert questions[1].question == "Which city would you like to work in?"
    assert questions[2].question == "What type of employment are you looking for?"
    assert [question.reason for question in questions] == [
        "Job directions define the search scope. Separate multiple directions with commas.",
        "Enter a city. If you have no location preference, answer “No preference.”",
        "For example, full-time, internship, or part-time. If you have no preference, answer “No preference.”",
    ]


def test_build_clarification_questions_localizes_the_generic_fallback() -> None:
    profile = build_from_input(complete_input()).model_copy(
        update={"missing_required_fields": ["preferences.salary_range"]}
    )

    questions = build_clarification_questions(profile)

    assert [question.field for question in questions] == ["preferences.salary_range"]
    assert questions[0].question == "Please provide information about preferences.salary_range."


def test_build_clarification_questions_localizes_the_skills_conflict() -> None:
    profile = build_from_input(conflicting_input()).model_copy(update={"conflicts": ["skills"]})
    questions = build_clarification_questions(profile)

    assert [question.field for question in questions] == ["skills"]
    assert questions[0].question.isascii()
    assert "complete" in questions[0].reason


def test_apply_answers_fills_required_gaps() -> None:
    profile = build_from_input(missing_input())
    questions = build_clarification_questions(profile)

    updated, updated_questions = apply_answers(
        profile,
        questions,
        {
            "target_directions": "data analyst, business analyst",
            "preferences.location": "不限",
            "preferences.employment_type": "实习",
        },
    )

    assert updated.target_directions == ["data analyst", "business analyst"]
    assert updated.preferences.location is None
    assert updated.preferences.location_unrestricted is True
    assert updated.preferences.employment_type == "internship"
    assert updated.missing_required_fields == []
    assert updated.confirmed_fields == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert all(question.status is ClarificationStatus.ANSWERED for question in updated_questions)
    assert updated_questions[0].answer == "data analyst, business analyst"


def test_apply_answers_resolves_the_skills_conflict() -> None:
    profile = build_from_input(conflicting_input()).model_copy(update={"conflicts": ["skills"]})
    questions = build_clarification_questions(profile)

    updated, updated_questions = apply_answers(
        profile,
        questions,
        {"skills": "Python, SQL, Java"},
    )

    assert updated.skills == ["Python", "SQL", "Java"]
    assert updated.conflicts == []
    assert updated.missing_required_fields == []
    assert updated_questions[0].status is ClarificationStatus.ANSWERED


def test_apply_answers_splits_space_separated_skills() -> None:
    profile = build_from_input(conflicting_input())
    questions = build_clarification_questions(profile)

    updated, _ = apply_answers(profile, questions, {"skills": "Python SQL Docker"})

    assert updated.skills == ["Python", "SQL", "Docker"]
    assert updated.conflicts == []


def test_apply_answers_keeps_unanswered_fields_pending() -> None:
    profile = build_from_input(missing_input())
    questions = build_clarification_questions(profile)

    updated, updated_questions = apply_answers(profile, questions, {"unknown": "value"})

    assert updated.missing_required_fields == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert updated.confirmed_fields == []
    assert all(question.status is ClarificationStatus.PENDING for question in updated_questions)


def test_apply_answers_accepts_an_unrestricted_employment_type() -> None:
    profile = build_from_input(missing_input())
    questions = build_clarification_questions(profile)

    updated, updated_questions = apply_answers(
        profile,
        questions,
        {
            "target_directions": "data analyst",
            "preferences.location": "Hong Kong",
            "preferences.employment_type": "不限",
        },
    )

    assert updated.preferences.employment_type == EMPLOYMENT_TYPE_UNRESTRICTED
    assert updated.missing_required_fields == []
    assert all(question.status is ClarificationStatus.ANSWERED for question in updated_questions)


def test_apply_answers_normalizes_english_employment_type_aliases() -> None:
    profile = build_from_input(missing_input())
    questions = build_clarification_questions(profile)

    updated, _ = apply_answers(profile, questions, {"preferences.employment_type": "Full Time"})

    assert updated.preferences.employment_type == "full-time"
    assert updated.missing_required_fields == [
        "target_directions",
        "preferences.location",
    ]


def test_apply_answers_normalizes_the_optional_work_mode() -> None:
    profile = build_from_input(complete_input())
    profile = profile.model_copy(update={"missing_required_fields": ["preferences.work_mode"]})
    questions = build_clarification_questions(profile)

    assert [question.field for question in questions] == ["preferences.work_mode"]

    updated, updated_questions = apply_answers(
        profile,
        questions,
        {"preferences.work_mode": "远程"},
    )

    assert updated.preferences.work_mode == "remote"
    assert updated.confirmed_fields == ["preferences.work_mode"]
    assert updated_questions[0].status is ClarificationStatus.ANSWERED

    cleared, _ = apply_answers(profile, questions, {"preferences.work_mode": "不限"})

    assert cleared.preferences.work_mode is None


def test_extract_profile_node_builds_a_profile_and_is_idempotent() -> None:
    update = extract_profile_node(make_state(input_data=complete_input()))

    assert update["profile"].profile_id == "session-1"
    assert update["profile"].target_directions == ["data engineer", "backend engineer"]
    assert update["current_stage"] == "profile"
    assert "warnings" not in update

    existing = build_from_input(complete_input(), profile_id="profile-2")
    again = extract_profile_node(make_state(input_data=complete_input(), profile=existing))

    assert "profile" not in again
    assert again["current_stage"] == "profile"


def test_extract_profile_node_warns_when_no_background_is_given() -> None:
    update = extract_profile_node(make_state(input_data=missing_input()))

    assert update["warnings"] == ["No resume or personal description was provided."]
    assert update["profile"].missing_required_fields == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]


def test_extract_profile_node_reports_invalid_input() -> None:
    update = extract_profile_node(make_state(input_data={"target_directions": 42}))

    assert update["errors"][0].code == "invalid_input"
    assert update["errors"][0].stage == "profile"
    assert "profile" not in update


def test_extract_profile_node_reports_a_non_mapping_input() -> None:
    update = extract_profile_node(make_state(input_data="target_directions=data analyst"))

    assert update["errors"][0].code == "invalid_input"
    assert update["errors"][0].message == "input_data must be an object."
    assert update["errors"][0].stage == "profile"
    assert "profile" not in update


def test_validate_profile_node_recomputes_missing_fields() -> None:
    stale = build_from_input(complete_input()).model_copy(
        update={"missing_required_fields": ["preferences.location"]}
    )

    update = validate_profile_node(make_state(profile=stale))

    assert update["current_stage"] == "validate"
    assert update["profile"].missing_required_fields == []


def test_validate_profile_node_without_profile_only_warns() -> None:
    update = validate_profile_node(make_state())

    assert update["warnings"] == ["No profile is available for validation."]
    assert "profile" not in update


def route_after_clarify(state: AgentState) -> str:
    """Local router: loop while a required question is still pending."""
    questions = state.get("clarification_questions") or []
    pending = any(
        question.required and question.status is ClarificationStatus.PENDING
        for question in questions
    )
    return "clarify" if pending else "done"


def build_clarification_graph() -> Any:
    """Compile a minimal graph that exercises the clarification pause/resume loop."""
    graph = StateGraph(AgentState)
    graph.add_node("clarify", cast(Any, clarification_node))
    graph.add_edge(START, "clarify")
    graph.add_conditional_edges(
        "clarify",
        cast(Any, route_after_clarify),
        {"clarify": "clarify", "done": END},
    )
    return graph.compile(checkpointer=InMemorySaver())


def test_clarification_node_pauses_then_applies_answers() -> None:
    graph = build_clarification_graph()
    config: Any = {"configurable": {"thread_id": "session-1"}}
    profile = build_from_input(missing_input())

    paused = graph.invoke(make_state(profile=profile), config)

    assert paused["current_stage"] == "clarify"
    assert [question.field for question in paused["clarification_questions"]] == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert graph.get_state(config).next == ("clarify",)
    assert paused["__interrupt__"][0].value["message"] == (
        "Answer the pending clarification questions to continue."
    )

    resumed = graph.invoke(
        Command(
            resume={
                "answers": {
                    "target_directions": "data analyst",
                    "preferences.location": "Hong Kong",
                    "preferences.employment_type": "full-time",
                }
            }
        ),
        config,
    )

    assert resumed["profile"].missing_required_fields == []
    assert resumed["profile"].preferences.location == "Hong Kong"
    assert resumed["profile"].confirmed_fields == [
        "target_directions",
        "preferences.location",
        "preferences.employment_type",
    ]
    assert all(
        question.status is ClarificationStatus.ANSWERED
        for question in resumed["clarification_questions"]
    )


def test_clarification_node_stays_paused_until_every_gap_is_answered() -> None:
    graph = build_clarification_graph()
    config: Any = {"configurable": {"thread_id": "session-2"}}
    profile = build_from_input(missing_input())

    graph.invoke(make_state(profile=profile), config)
    partial = graph.invoke(
        Command(resume={"answers": {"preferences.location": "Hong Kong"}}),
        config,
    )

    statuses = [question.status for question in partial["clarification_questions"]]
    assert statuses == [
        ClarificationStatus.PENDING,
        ClarificationStatus.ANSWERED,
        ClarificationStatus.PENDING,
    ]
    assert partial["profile"].missing_required_fields == [
        "target_directions",
        "preferences.employment_type",
    ]
    assert graph.get_state(config).next == ("clarify",)


def build_profile_graph() -> Any:
    """Compile these nodes behind the shared workflow routers from the workflow group."""
    graph = StateGraph(AgentState)
    graph.add_node("profile", cast(Any, extract_profile_node))
    graph.add_node("validate", cast(Any, validate_profile_node))
    graph.add_node("clarify", cast(Any, clarification_node))
    graph.add_edge(START, "profile")
    graph.add_edge("profile", "validate")
    graph.add_conditional_edges(
        "validate",
        cast(Any, route_after_validation),
        {"clarify": "clarify", "search": END, "failed": END},
    )
    graph.add_conditional_edges(
        "clarify",
        cast(Any, route_after_clarification),
        {"clarify": "clarify", "validate": "validate", "failed": END},
    )
    return graph.compile(checkpointer=InMemorySaver())


def test_profile_nodes_pause_and_resume_through_the_shared_routers() -> None:
    graph = build_profile_graph()
    config: Any = {"configurable": {"thread_id": "session-3"}}

    paused = graph.invoke(make_state(input_data=missing_input()), config)

    assert paused["current_stage"] == "clarify"
    assert graph.get_state(config).next == ("clarify",)

    resumed = graph.invoke(
        Command(
            resume={
                "answers": {
                    "target_directions": "data analyst",
                    "preferences.location": "Hong Kong",
                    "preferences.employment_type": "full-time",
                }
            }
        ),
        config,
    )

    assert resumed["current_stage"] == "validate"
    assert resumed["profile"].missing_required_fields == []
    assert resumed["profile"].target_directions == ["data analyst"]
    assert graph.get_state(config).next == ()


def test_unrestricted_employment_type_converges_through_the_shared_routers() -> None:
    graph = build_profile_graph()
    config: Any = {"configurable": {"thread_id": "session-4"}}

    graph.invoke(make_state(input_data=missing_input()), config)
    resumed = graph.invoke(
        Command(
            resume={
                "answers": {
                    "target_directions": "data analyst",
                    "preferences.location": "不限",
                    "preferences.employment_type": "不限",
                }
            }
        ),
        config,
    )

    assert resumed["profile"].preferences.employment_type == EMPLOYMENT_TYPE_UNRESTRICTED
    assert resumed["profile"].missing_required_fields == []
    assert resumed["current_stage"] == "validate"
    assert graph.get_state(config).next == ()


def build_router_clarification_graph() -> Any:
    """Compile the clarification node behind the shared clarification router."""
    graph = StateGraph(AgentState)
    graph.add_node("clarify", cast(Any, clarification_node))
    graph.add_edge(START, "clarify")
    graph.add_conditional_edges(
        "clarify",
        cast(Any, route_after_clarification),
        {"clarify": "clarify", "validate": END, "failed": END},
    )
    return graph.compile(checkpointer=InMemorySaver())


def test_clarification_node_fails_the_session_when_the_profile_is_missing() -> None:
    graph = build_router_clarification_graph()
    config: Any = {"configurable": {"thread_id": "session-5"}}

    graph.invoke(make_state(clarification_questions=build_clarification_questions(None)), config)
    resumed = graph.invoke(
        Command(resume={"answers": {"target_directions": "data analyst"}}),
        config,
    )

    assert resumed["errors"][0].code == "invalid_input"
    assert resumed["errors"][0].message == "No profile is available to update."
    assert resumed["errors"][0].stage == "clarify"
    assert resumed["current_stage"] == "clarify"
    assert graph.get_state(config).next == ()
