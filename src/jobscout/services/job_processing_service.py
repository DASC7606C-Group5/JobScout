"""Normalize raw jobs, deduplicate postings, and classify freshness.

Group 5 (job understanding & data quality) owns this module. It converts the
raw job records returned by Group 4's retrieval into the frozen ``JobPosting``
contract (``jobscout/schemas/job.py``, schema v1 maintained by Group 3),
merges cross-source duplicates while preserving every source link, and marks
each posting as ``active`` / ``expired`` / ``unknown``. Freshness is never
guessed: without explicit evidence a posting stays ``unknown``.

Missing-field handling follows the contract decision confirmed on 2026-09-30:

- records missing any contract-required field (``title``, ``company``,
  ``source_url``, ``location``, ``target_direction``, ``fetched_at``) are
  dropped with a warning — a posting without them cannot be constructed,
  displayed, or deduplicated reliably;
- optional fields (``salary``, ``posted_at``, ``expiry_at``) stay ``None``
  with a warning instead of being fabricated;
- a missing ``job_id`` is replaced by a stable id derived from the dedup key;
  a missing ``source`` falls back to ``"unknown"`` with a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, NamedTuple

from jobscout.schemas.job import FreshnessStatus, JobPosting

# Section headers recognized when parsing a free-text job description (JD).
_RESPONSIBILITY_HEADERS = (
    "responsibilities",
    "responsibility",
    "what you'll do",
    "what you will do",
    "your role",
    "duties",
    "key responsibilities",
)
_SKILL_HEADERS = (
    "requirements",
    "requirement",
    "qualifications",
    "qualification",
    "skills",
    "required skills",
    "what we're looking for",
    "what we are looking for",
    "preferred qualifications",
)

# Fallback lexicon used only when the JD has no recognizable skills section.
_SKILL_LEXICON = (
    "Python",
    "SQL",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "Pandas",
    "NumPy",
    "R",
    "Excel",
    "Tableau",
    "Power BI",
    "Machine Learning",
    "Deep Learning",
    "NLP",
    "Statistics",
    "Spark",
    "Hadoop",
    "Docker",
    "Kubernetes",
    "Git",
    "Linux",
    "AWS",
    "GCP",
    "Azure",
    "C++",
    "C#",
    "Go",
    "Rust",
    "Scala",
    "Matlab",
    "SAS",
    "SPSS",
    "Figma",
    "Sketch",
    "Photoshop",
    "AutoCAD",
    "SolidWorks",
    "PLC",
    "CAD",
    "SEO",
    "SEM",
    "CRM",
    "ERP",
    "SAP",
    "Salesforce",
    "Cantonese",
    "Mandarin",
    "English",
)

# Text fields the frozen JobPosting contract requires; a raw record missing
# any of them is dropped with a warning. ``fetched_at`` is also required but
# validated separately because it must parse as a datetime.
_REQUIRED_TEXT_FIELDS = ("title", "company", "source_url", "location", "target_direction")

_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•·▪◦‣·]|\d+[.)])\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class ProcessingResult(NamedTuple):
    """Output of :func:`process_jobs`: normalized postings plus data-quality warnings.

    Supports both attribute access (``result.jobs``) and tuple unpacking
    (``jobs, warnings = process_jobs(...)``).
    """

    jobs: list[JobPosting]
    warnings: list[str]


def _clean_text(value: object) -> str | None:
    """Normalize whitespace; return ``None`` for missing or blank values."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clean_description(value: object) -> str | None:
    """Like :func:`_clean_text` but keeps line structure for section parsing."""
    if not isinstance(value, str):
        return None
    lines = [" ".join(line.split()) for line in value.splitlines()]
    cleaned = "\n".join(lines).strip("\n")
    return cleaned or None


def _clean_salary(value: object) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _clean_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        cleaned = _clean_text(entry)
        if cleaned is not None:
            items.append(cleaned)
    return items


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _parse_datetime(value: object) -> datetime | None:
    """Parse an ISO-8601 string or datetime; naive values are assumed UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _dedup_key_part(value: str | None) -> str:
    if value is None:
        return ""
    return _NON_ALNUM.sub(" ", value.casefold()).strip()


def _is_header_line(line: str, headers: tuple[str, ...]) -> bool:
    text = line.strip().rstrip(":").strip().casefold()
    return text in headers


def _looks_like_header(line: str) -> bool:
    text = line.strip()
    return text.endswith(":") and len(text.split()) <= 5


def _extract_section_items(description: str, headers: tuple[str, ...]) -> list[str]:
    """Collect bullet/short lines under the first matching section header."""
    lines = description.splitlines()
    items: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_section and items:
                break
            continue
        if _is_header_line(stripped, headers):
            in_section = True
            continue
        if in_section:
            if _looks_like_header(stripped) and not _BULLET_PREFIX.match(stripped):
                break
            item = _clean_text(_BULLET_PREFIX.sub("", stripped))
            if item is not None:
                items.append(item)
    return items


def _lexicon_skills(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.casefold()
    for skill in _SKILL_LEXICON:
        if re.search(r"(?<![a-z0-9+#])" + re.escape(skill.casefold()) + r"(?![a-z0-9])", lowered):
            found.append(skill)
    return found


def _parse_responsibilities(raw: dict[str, Any], description: str | None) -> list[str]:
    explicit = _clean_str_list(raw.get("responsibilities"))
    if explicit:
        return _dedupe_keep_order(explicit)
    if description:
        return _dedupe_keep_order(_extract_section_items(description, _RESPONSIBILITY_HEADERS))
    return []


def _parse_required_skills(raw: dict[str, Any], description: str | None) -> list[str]:
    explicit = _clean_str_list(raw.get("required_skills"))
    if explicit:
        return _dedupe_keep_order(explicit)
    if description:
        section = _extract_section_items(description, _SKILL_HEADERS)
        if section:
            return _dedupe_keep_order(section)
        return _lexicon_skills(description)
    return []


def _normalize_status(value: object) -> FreshnessStatus | None:
    """Return the explicit source status, or ``None`` when absent or unrecognized."""
    if not isinstance(value, str):
        return None
    try:
        return FreshnessStatus(value.strip().casefold())
    except ValueError:
        return None


def _classify_freshness(
    expiry_at: datetime | None,
    raw_statuses: list[FreshnessStatus],
    now: datetime,
) -> FreshnessStatus:
    """Decide freshness from evidence only; never guess ``active``.

    Precedence: an expiry timestamp decides first; otherwise an explicit
    source status is honored (a conflicting ``expired`` beats ``active`` when
    duplicates disagree); without either the posting is ``unknown``.
    A ``posted_at`` date alone is never treated as proof of freshness.
    """
    if expiry_at is not None:
        return FreshnessStatus.EXPIRED if expiry_at < now else FreshnessStatus.ACTIVE
    if FreshnessStatus.EXPIRED in raw_statuses:
        return FreshnessStatus.EXPIRED
    if FreshnessStatus.ACTIVE in raw_statuses:
        return FreshnessStatus.ACTIVE
    return FreshnessStatus.UNKNOWN


@dataclass
class _Group:
    """Mutable accumulator for one dedup group of raw records."""

    records: list[dict[str, Any]] = field(default_factory=list)
    raw_statuses: list[FreshnessStatus] = field(default_factory=list)


def process_jobs(
    raw_jobs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> ProcessingResult:
    """Normalize, deduplicate, and freshness-classify raw job records.

    Args:
        raw_jobs: Raw records from retrieval (Group 4). Each record is a dict
            with fields like ``job_id``, ``source``, ``source_url``, ``title``,
            ``company``, ``location``, ``salary``, ``target_direction``,
            ``responsibilities``, ``required_skills``, ``description``,
            ``posted_at``, ``expiry_at``, ``freshness_status``, ``fetched_at``
            and ``source_links``.
        now: Reference time for freshness classification (tests inject a fixed
            value); defaults to the current UTC time.

    Returns:
        A :class:`ProcessingResult` of unified ``JobPosting`` objects and
        data-quality warnings; unpacks as ``jobs, warnings``.

    Records missing a contract-required field (``title``, ``company``,
    ``source_url``, ``location``, ``target_direction`` or a parseable
    ``fetched_at``) are dropped with one warning per record. Missing optional
    fields (``salary``, ``posted_at``, ``expiry_at``) stay ``None`` with a
    warning. A single broken record never fails the batch.

    Duplicates are merged by normalized (company, title, location): the merged
    posting keeps every source link, unions responsibilities and skills, and
    prefers non-empty fields from the first record that provides them.
    """
    reference_now = now if now is not None else datetime.now(UTC)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=UTC)

    warnings: list[str] = []
    groups: dict[tuple[str, str, str], _Group] = {}
    order: list[tuple[str, str, str]] = []

    for index, raw in enumerate(raw_jobs):
        label = _clean_text(raw.get("job_id")) or f"index {index}"
        missing = [name for name in _REQUIRED_TEXT_FIELDS if _clean_text(raw.get(name)) is None]
        if _parse_datetime(raw.get("fetched_at")) is None:
            missing.append("fetched_at")
        if missing:
            warnings.append(
                f"Dropped record {label}: missing required field(s): {', '.join(missing)}."
            )
            continue

        title = _clean_text(raw.get("title")) or ""
        company = _clean_text(raw.get("company")) or ""
        if _clean_text(raw.get("source")) is None:
            warnings.append(
                f"Record {label} ({title} @ {company}): missing source; kept as unknown."
            )
        if _clean_salary(raw.get("salary")) is None:
            warnings.append(f"Record {label} ({title} @ {company}): missing salary; kept as None.")
        if _parse_datetime(raw.get("posted_at")) is None:
            warnings.append(
                f"Record {label} ({title} @ {company}): missing posted_at; kept as None."
            )
        if _parse_datetime(raw.get("expiry_at")) is None:
            warnings.append(
                f"Record {label} ({title} @ {company}): missing expiry_at; kept as None."
            )

        location = _clean_text(raw.get("location"))
        key = (_dedup_key_part(company), _dedup_key_part(title), _dedup_key_part(location))
        group = groups.get(key)
        if group is None:
            group = _Group()
            groups[key] = group
            order.append(key)
        group.records.append(raw)
        status = _normalize_status(raw.get("freshness_status"))
        if status is not None:
            group.raw_statuses.append(status)

    jobs: list[JobPosting] = []
    for key in order:
        records = groups[key].records
        first = records[0]

        responsibilities = _dedupe_keep_order(
            [
                item
                for raw in records
                for item in _parse_responsibilities(raw, _clean_description(raw.get("description")))
            ]
        )
        required_skills = _dedupe_keep_order(
            [
                item
                for raw in records
                for item in _parse_required_skills(raw, _clean_description(raw.get("description")))
            ]
        )

        source_links = _dedupe_keep_order(
            [
                link
                for raw in records
                for link in (
                    [_clean_text(raw.get("source_url"))] + _clean_str_list(raw.get("source_links"))
                )
                if link is not None
            ]
        )

        sources = _dedupe_keep_order(
            [source for raw in records if (source := _clean_text(raw.get("source"))) is not None]
        )
        timestamps = [ts for raw in records if (ts := _parse_datetime(raw.get("posted_at")))]
        expiries = [ts for raw in records if (ts := _parse_datetime(raw.get("expiry_at")))]
        fetches = [ts for raw in records if (ts := _parse_datetime(raw.get("fetched_at")))]

        job_id = _clean_text(first.get("job_id"))
        if job_id is None:
            job_id = "gen-" + sha256("|".join(key).encode("utf-8")).hexdigest()[:16]

        title = _clean_text(first.get("title")) or ""
        company = _clean_text(first.get("company")) or ""
        if not responsibilities and not required_skills:
            warnings.append(
                f"Merged job {job_id} ({title} @ {company}): "
                "no responsibilities or required skills extracted."
            )

        jobs.append(
            JobPosting(
                job_id=job_id,
                source=", ".join(sources) if sources else "unknown",
                source_url=source_links[0],
                title=title,
                company=company,
                location=_clean_text(first.get("location")) or "",
                salary=next(
                    (
                        salary
                        for raw in records
                        if (salary := _clean_salary(raw.get("salary"))) is not None
                    ),
                    None,
                ),
                target_direction=_clean_text(first.get("target_direction")) or "",
                responsibilities=responsibilities,
                required_skills=required_skills,
                posted_at=min(timestamps) if timestamps else None,
                expiry_at=min(expiries) if expiries else None,
                freshness_status=_classify_freshness(
                    min(expiries) if expiries else None,
                    groups[key].raw_statuses,
                    reference_now,
                ),
                fetched_at=max(fetches),
                source_links=source_links,
            )
        )

    return ProcessingResult(jobs=jobs, warnings=warnings)
