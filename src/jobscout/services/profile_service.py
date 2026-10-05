"""Deterministic profile extraction, merging, validation, and answer write-back.

This module implements the second workstream ("user profile and confirmation").
It converts the standardized frontend input into the frozen ``UserProfile``
contract, reports missing required fields and unresolved conflicts, and builds
the clarification questions consumed by the workflow and the session API.

The extraction is deliberately rule based: no network or model call is made, so
results stay deterministic and unit-testable. Replacing the rules with a
schema-constrained model call later must keep these signatures and the
``UserProfile`` contract unchanged.

A "no preference" answer for ``preferences.employment_type`` is stored as the
sentinel ``EMPLOYMENT_TYPE_UNRESTRICTED`` instead of being dropped, so a blocking
question can always be answered and the clarification loop always terminates.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypedDict

from pydantic import ValidationError

from jobscout.schemas.profile import ProfilePreferences, ProfileSource, UserProfile
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus


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


_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s*")
_MARKDOWN_MARKS = re.compile(r"[*_`]")
_WHITESPACE = re.compile(r"\s+")
_LIST_SEPARATOR = re.compile(r"[,，、;；/|]")
_TRAILING_SEPARATOR = "；;，,、"

_SECTION_KEYWORDS: dict[str, frozenset[str]] = {
    "education": frozenset(
        {
            "education",
            "education background",
            "educational background",
            "academic background",
            "学历",
            "教育",
            "教育背景",
            "教育经历",
        }
    ),
    "skills": frozenset(
        {
            "skill",
            "skills",
            "core skills",
            "technical skills",
            "tech stack",
            "技能",
            "技能清单",
            "技术栈",
        }
    ),
    "internships": frozenset(
        {
            "experience",
            "internship",
            "internships",
            "professional experience",
            "work experience",
            "实习",
            "实习经历",
            "实习经验",
            "工作经历",
            "任职经历",
            "实践经历",
        }
    ),
    "projects": frozenset(
        {
            "project",
            "project experience",
            "projects",
            "项目",
            "项目经历",
            "项目经验",
            "个人项目",
            "个人项目经历",
        }
    ),
}

_SKILL_VOCABULARY: dict[str, str] = {
    "aws": "AWS",
    "azure": "Azure",
    "c#": "C#",
    "c++": "C++",
    "css": "CSS",
    "data analysis": "Data Analysis",
    "data engineering": "Data Engineering",
    "data visualization": "Data Visualization",
    "deep learning": "Deep Learning",
    "django": "Django",
    "docker": "Docker",
    "excel": "Excel",
    "fastapi": "FastAPI",
    "figma": "Figma",
    "flask": "Flask",
    "gcp": "GCP",
    "git": "Git",
    "golang": "Golang",
    "hadoop": "Hadoop",
    "html": "HTML",
    "java": "Java",
    "javascript": "JavaScript",
    "k8s": "Kubernetes",
    "kotlin": "Kotlin",
    "kubernetes": "Kubernetes",
    "linux": "Linux",
    "machine learning": "Machine Learning",
    "mongodb": "MongoDB",
    "mysql": "MySQL",
    "nlp": "NLP",
    "node.js": "Node.js",
    "numpy": "NumPy",
    "pandas": "pandas",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "python": "Python",
    "pytorch": "PyTorch",
    "react": "React",
    "redis": "Redis",
    "scikit-learn": "scikit-learn",
    "spark": "Spark",
    "spring boot": "Spring Boot",
    "sql": "SQL",
    "statistics": "Statistics",
    "swift": "Swift",
    "tableau": "Tableau",
    "tailwind css": "Tailwind CSS",
    "tensorflow": "TensorFlow",
    "typescript": "TypeScript",
}


@dataclass(frozen=True)
class Background:
    """Education, skills, internships, and projects parsed from one text block."""

    education: list[str]
    skills: list[str]
    internships: list[str]
    projects: list[str]


_EMPTY_BACKGROUND = Background(education=[], skills=[], internships=[], projects=[])


def extract_background(text: str) -> Background:
    """Extract background sections from one text block.

    Heading based parsing runs first, then a fixed skill vocabulary is scanned
    over the whole text so free-form descriptions still contribute skills.
    Unknown bare headings are treated as body text; this is an accepted MVP limit.

    Args:
        text: Resume text or free-text personal description.

    Returns:
        Parsed background with de-duplicated entries in first-seen order.
    """
    sections = _split_sections(text)
    skills = [
        *_parse_skill_tokens(sections.get("skills", [])),
        *_scan_skill_vocabulary(text),
    ]
    return Background(
        education=_parse_entries(sections.get("education", [])),
        skills=dedupe(skills),
        internships=_parse_entries(sections.get("internships", [])),
        projects=_parse_entries(sections.get("projects", [])),
    )


def merge_backgrounds(backgrounds: Iterable[Background]) -> Background:
    """Merge several backgrounds, de-duplicating each field case-insensitively.

    Args:
        backgrounds: Backgrounds in priority order; earlier entries win ties.

    Returns:
        A single merged background.
    """
    education: list[str] = []
    skills: list[str] = []
    internships: list[str] = []
    projects: list[str] = []
    for background in backgrounds:
        education.extend(background.education)
        skills.extend(background.skills)
        internships.extend(background.internships)
        projects.extend(background.projects)
    return Background(
        education=dedupe(education),
        skills=dedupe(skills),
        internships=dedupe(internships),
        projects=dedupe(projects),
    )


def detect_conflicts(
    resume_background: Background,
    description_background: Background,
) -> list[str]:
    """Report profile fields where resume and description cannot be reconciled.

    Skill lists contain positive claims, so different lists are complementary,
    not contradictory. The live understanding service handles explicit negations
    and corrections using the original text; this lossy background cannot.

    Args:
        resume_background: Background parsed from the resume.
        description_background: Background parsed from the personal description.

    Returns:
        Field names awaiting user confirmation, in a stable order.
    """
    return []


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


def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        section = _canonical_section(raw_line)
        if section is not None:
            current = section
            sections.setdefault(section, [])
            continue
        if _is_header(raw_line):
            current = None
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def _canonical_section(line: str) -> str | None:
    header = _normalize_header(line)
    for section, keywords in _SECTION_KEYWORDS.items():
        if header in keywords:
            return section
    return None


def _normalize_header(line: str) -> str:
    without_marks = _MARKDOWN_MARKS.sub("", line)
    collapsed = _WHITESPACE.sub(" ", without_marks).strip()
    return collapsed.strip(":：").strip().casefold()


def _is_header(line: str) -> bool:
    """Report whether a line is a markdown heading that ends the current section.

    A trailing colon is deliberately *not* treated as a heading. Labels such as
    ``Responsibilities:`` commonly appear inside a section, and ending the section
    there used to drop every line that followed (see the problem list B7).
    """
    return line.strip().startswith("#")


def _clean_line(line: str) -> str:
    without_bullet = _BULLET_PREFIX.sub("", line)
    return _MARKDOWN_MARKS.sub("", without_bullet).strip()


def _parse_entries(lines: Iterable[str]) -> list[str]:
    entries: list[str] = []
    for line in lines:
        cleaned = _clean_line(line).rstrip(_TRAILING_SEPARATOR).strip()
        if cleaned:
            entries.append(cleaned)
    return dedupe(entries)


def _parse_skill_tokens(lines: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    for line in lines:
        for part in _LIST_SEPARATOR.split(_clean_line(line)):
            token = part.strip().strip(".。").strip()
            if token:
                tokens.extend(_split_skill_token(token))
    return dedupe(tokens)


def _split_skill_token(token: str) -> list[str]:
    """Split one delimited token that actually packs several known skills.

    ``"Python SQL Docker"`` becomes three skills, but a token is only split when
    every whitespace separated part is a known skill and at least two parts are
    known. Unknown multi-word skills such as ``"Looker Studio"`` therefore stay
    intact, because neither source may silently lose a skill.

    Args:
        token: One skill candidate that was already split on list separators.

    Returns:
        ``[token]`` when the token is one skill, or the individual words to keep.
    """
    if token.casefold() in _SKILL_VOCABULARY:
        return [token]
    words = token.split()
    if len(words) < 2:
        return [token]
    known = sum(1 for word in words if word.casefold() in _SKILL_VOCABULARY)
    if known < 2 or known != len(words):
        return [token]
    return words


def _scan_skill_vocabulary(text: str) -> list[str]:
    """Return vocabulary skills found in ``text``, ordered by first appearance.

    Scanning the whole text keeps free-form descriptions contributing skills. The
    order follows the position of the first match so the merged list matches the
    order the user wrote, instead of the fixed vocabulary order (see B4).
    """
    if not text:
        return []
    lowered = text.casefold()
    matched: list[tuple[int, str]] = []
    for keyword, display in _SKILL_VOCABULARY.items():
        pattern = rf"(?<![a-z0-9+#.]){re.escape(keyword)}(?![a-z0-9+#])"
        found = re.search(pattern, lowered)
        if found is not None:
            matched.append((found.start(), display))
    matched.sort(key=lambda item: item[0])
    return [display for _, display in matched]


def required_missing_fields(profile: UserProfile) -> list[str]:
    """List the profile fields that block job search until they are answered.

    A background source (resume or description) is required by the guide, but it
    is reported as a node warning instead of a blocking clarification question,
    because the available question set covers directions, location, and type.

    Args:
        profile: Profile produced by extraction or answer write-back.

    Returns:
        Missing required field names in a stable order.
    """
    missing: list[str] = []
    if not any(direction.strip() for direction in profile.target_directions):
        missing.append("target_directions")
    preferences = profile.preferences
    if not _has_text(preferences.location) and not preferences.location_unrestricted:
        missing.append("preferences.location")
    if not _has_text(preferences.employment_type) and not preferences.employment_type_unrestricted:
        missing.append("preferences.employment_type")
    return missing


def build_profile(
    profile_id: str,
    *,
    description: str = "",
    resume: ResumeFile | None = None,
    target_directions: Iterable[str] = (),
    preferences: ProfilePreferences | None = None,
) -> UserProfile:
    """Build a frozen ``UserProfile`` from standardized user input.

    Resume and description backgrounds are merged, conflicts are recorded
    without overwriting either source, and required-field gaps are computed.

    Args:
        profile_id: Identifier assigned to the produced profile.
        description: Free-text personal description.
        resume: Parsed resume payload, or None when no resume was provided.
        target_directions: Target job directions supplied by the user.
        preferences: Location, employment type, and optional preferences.

    Returns:
        A ``UserProfile`` with source flags, background, conflicts, and gaps.
    """
    description_text = description.strip()
    resume_background = (
        extract_background(resume["text"]) if resume is not None else _EMPTY_BACKGROUND
    )
    description_background = (
        extract_background(description_text) if description_text else _EMPTY_BACKGROUND
    )
    merged = merge_backgrounds([resume_background, description_background])
    profile = UserProfile(
        profile_id=profile_id,
        source=ProfileSource(
            resume=resume is not None,
            description=bool(description_text),
        ),
        education=merged.education,
        skills=merged.skills,
        internships=merged.internships,
        projects=merged.projects,
        target_directions=dedupe(
            direction.strip() for direction in target_directions if direction.strip()
        ),
        preferences=preferences.model_copy() if preferences is not None else ProfilePreferences(),
        conflicts=detect_conflicts(resume_background, description_background),
    )
    return profile.model_copy(update={"missing_required_fields": required_missing_fields(profile)})


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


# User-visible question copy. The frontend renders ``question`` and ``reason``
# verbatim, so this text is Chinese and stays aligned with the copy used by the
# demo adapter in ``web/src/lib/session-client.ts``.
_MISSING_FIELD_QUESTIONS: dict[str, tuple[str, str]] = {
    "target_directions": (
        "你希望寻找哪一类岗位？",
        "求职方向用于确定搜索范围；多个方向可以用逗号分隔。",
    ),
    "preferences.location": (
        "你希望在哪个城市工作？",
        "请填写城市；如果没有地点偏好，可以回答“不限”。",
    ),
    "preferences.employment_type": (
        "你更倾向哪种工作类型？",
        "例如全职、实习或兼职；如果没有偏好，可以回答“不限”。",
    ),
    "preferences.work_mode": (
        "你对工作方式有什么偏好？",
        "可以选择办公室、混合办公、远程，或者回答“不限”。",
    ),
}

_CONFLICT_QUESTIONS: dict[str, tuple[str, str]] = {
    "skills": (
        "你的简历和个人描述里提到的技能不一致，应该以哪一份为准？",
        "请给出完整的技能列表，回答会整体替换当前的技能集合。",
    ),
}


def build_clarification_questions(profile: UserProfile | None) -> list[ClarificationMessage]:
    """Build the questions that the workflow asks before searching.

    Args:
        profile: Current profile, or None when extraction produced no profile.

    Returns:
        Pending clarification messages, one per blocking field, de-duplicated.
    """
    fields: list[str] = []
    if profile is None:
        fields.append("target_directions")
    else:
        fields.extend(profile.missing_required_fields)
        fields.extend(profile.conflicts)

    questions: list[ClarificationMessage] = []
    for field in dedupe(fields):
        template = _MISSING_FIELD_QUESTIONS.get(field) or _CONFLICT_QUESTIONS.get(field)
        question, reason = template if template is not None else _generic_question(field)
        questions.append(ClarificationMessage(question=question, field=field, reason=reason))
    return questions


def _generic_question(field: str) -> tuple[str, str]:
    """Fallback copy for a field that has no curated question template."""
    return (
        f"请补充「{field}」的相关信息。",
        "该字段是开始岗位检索前必须确认的信息。",
    )


EMPLOYMENT_TYPE_UNRESTRICTED = "unrestricted"
# Value stored in ``preferences.employment_type`` when the user accepts any
# employment type (``不限``). That field is free text, so unlike
# ``location_unrestricted`` the "no preference" state lives in the value itself.
# Keeping the field non-empty is what lets the blocking question resolve instead
# of being asked forever (see the problem list B9).

_UNRESTRICTED_ANSWERS = frozenset(
    {"不限", "any", "anywhere", "no preference", "none", "unrestricted"}
)

_EMPLOYMENT_TYPE_ALIASES: dict[str, str] = {
    "全职": "full-time",
    "实习": "internship",
    "兼职": "part-time",
    "full time": "full-time",
    "fulltime": "full-time",
    "part time": "part-time",
    "parttime": "part-time",
}

_WORK_MODE_ALIASES: dict[str, str] = {
    "办公室": "onsite",
    "混合办公": "hybrid",
    "远程": "remote",
    "office": "onsite",
    "onsite": "onsite",
    "hybrid": "hybrid",
    "remote": "remote",
}


def apply_answers(
    profile: UserProfile,
    questions: Iterable[ClarificationMessage],
    answers: Mapping[str, object],
) -> tuple[UserProfile, list[ClarificationMessage]]:
    """Write clarification answers back into the profile and question list.

    Unknown fields and blank answers are ignored, so a resumed session with an
    incomplete answer payload keeps the blocking questions pending instead of
    confirming information the user never gave.

    Args:
        profile: Profile the questions were generated from.
        questions: Pending clarification messages for this session.
        answers: Mapping of profile field name to the user's answer text.

    Returns:
        The updated profile and questions, with gaps and conflicts recomputed.
    """
    preferences = profile.preferences.model_copy()
    target_directions = list(profile.target_directions)
    skills = list(profile.skills)
    conflicts = list(profile.conflicts)
    answered_fields: list[str] = []
    normalized_answers: dict[str, str] = {}

    for field, raw_answer in answers.items():
        answer = raw_answer.strip() if isinstance(raw_answer, str) else ""
        if not answer:
            continue
        if field == "target_directions":
            directions = split_list_text(answer)
            if not directions:
                continue
            target_directions = directions
        elif field == "preferences.location":
            preferences.location_unrestricted = _is_unrestricted_answer(answer)
            preferences.location = None if preferences.location_unrestricted else answer
        elif field == "preferences.employment_type":
            preferences.employment_type = _normalize_employment_type(answer)
            preferences.employment_type_unrestricted = _is_unrestricted_answer(answer)
        elif field == "preferences.work_mode":
            preferences.work_mode = _normalize_work_mode(answer)
        elif field == "preferences.salary_range":
            preferences.salary_range = answer
        elif field == "preferences.industry":
            preferences.industry = answer
        elif field == "skills":
            confirmed_skills = dedupe(
                part for token in split_list_text(answer) for part in _split_skill_token(token)
            )
            if not confirmed_skills:
                continue
            skills = confirmed_skills
            conflicts = [item for item in conflicts if item != "skills"]
        else:
            continue
        answered_fields.append(field)
        normalized_answers[field] = answer

    updated_profile = profile.model_copy(
        update={
            "target_directions": target_directions,
            "skills": skills,
            "preferences": preferences,
            "conflicts": conflicts,
            "confirmed_fields": dedupe([*profile.confirmed_fields, *answered_fields]),
        }
    )
    updated_profile = updated_profile.model_copy(
        update={"missing_required_fields": required_missing_fields(updated_profile)}
    )
    updated_questions = [
        question.model_copy(
            update={
                "status": ClarificationStatus.ANSWERED,
                "answer": normalized_answers[question.field],
            }
        )
        if question.field in normalized_answers
        else question
        for question in questions
    ]
    return updated_profile, updated_questions


def _is_unrestricted_answer(answer: str) -> bool:
    return answer.strip().casefold() in _UNRESTRICTED_ANSWERS


def _normalize_employment_type(answer: str) -> str:
    """Normalize an employment type answer into the stored value.

    A "no preference" answer maps to ``EMPLOYMENT_TYPE_UNRESTRICTED`` instead of
    being ignored, so the blocking question can be answered and the workflow
    converges instead of looping forever (see the problem list B9).

    Args:
        answer: Raw answer text supplied for ``preferences.employment_type``.

    Returns:
        The normalized employment type value, never blank.
    """
    stripped = answer.strip()
    if _is_unrestricted_answer(stripped):
        return EMPLOYMENT_TYPE_UNRESTRICTED
    return _EMPLOYMENT_TYPE_ALIASES.get(stripped.casefold(), stripped)


def _normalize_work_mode(answer: str) -> str | None:
    if _is_unrestricted_answer(answer):
        return None
    return _WORK_MODE_ALIASES.get(answer.strip().casefold(), answer.strip())
