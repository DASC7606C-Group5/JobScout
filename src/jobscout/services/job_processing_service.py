"""Normalize raw jobs, deduplicate postings, and classify freshness.

It converts raw retrieval records into the shared ``JobPosting`` contract,
retains source-specific documents and all matched directions,
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
import unicodedata
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any, NamedTuple

from pydantic import ValidationError

from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument

# Section headers recognized when parsing a free-text job description (JD).
_RESPONSIBILITY_HEADERS = (
    "responsibilities",
    "responsibility",
    "what you'll do",
    "what you will do",
    "your role",
    "duties",
    "key responsibilities",
    "岗位职责",
    "工作职责",
    "職位職責",
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
    "任职要求",
    "岗位要求",
    "任職要求",
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
# Unicode-aware: keeps CJK and other non-ASCII letters/digits so Chinese
# (company, title, location) triples do not collapse into empty dedup keys.
_NON_ALNUM = re.compile(r"[\W_]+")


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


_HTML_BLOCK_TAGS = frozenset(
    {"br", "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"}
)


class _DescriptionParser(HTMLParser):
    """Decode HTML text while preserving blocks and excluding scripts/styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if not self.hidden_depth and tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        if not self.hidden_depth and tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _html_description_text(value: str) -> str:
    if not re.search(r"</?[a-zA-Z][^>]*>", value):
        return value
    parser = _DescriptionParser()
    parser.feed(value)
    parser.close()
    # Adjacent block tags should not create blank lines ending a section.
    return re.sub(r"\n\s*\n", "\n", "".join(parser.parts))


def _clean_description(value: object) -> str | None:
    """Like :func:`_clean_text` but keeps line structure for section parsing."""
    if not isinstance(value, str):
        return None
    value = _html_description_text(value)
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
    # NFKC folds full-width/half-width variants (e.g. "Ａｃｍｅ" → "Acme")
    # before case folding, so equivalent forms share one dedup key.
    normalized = unicodedata.normalize("NFKC", value)
    return _NON_ALNUM.sub(" ", normalized.casefold()).strip()


def _is_header_line(line: str, headers: tuple[str, ...]) -> bool:
    line = line.rstrip().removesuffix("：")
    text = line.strip().rstrip(":").strip().casefold()
    return text in headers


def _looks_like_header(line: str) -> bool:
    line = line.replace("：", ":")
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


def _record_quality_warnings(raw: dict[str, Any], label: str, now: datetime) -> list[str]:
    """Report source quality and conflicts without changing normalization rules."""
    warnings: list[str] = []
    expiry = _parse_datetime(raw.get("expiry_at"))
    status = _normalize_status(raw.get("freshness_status"))
    if expiry is not None and status in (FreshnessStatus.ACTIVE, FreshnessStatus.EXPIRED):
        if status is not _classify_freshness(expiry, [], now):
            warnings.append(
                f"Record {label}: expiry_at conflicts with freshness_status "
                f"{status.value}; expiry_at takes precedence."
            )
    return warnings


def _status_conflict_warnings(job_id: str, statuses: list[FreshnessStatus]) -> list[str]:
    if {FreshnessStatus.ACTIVE, FreshnessStatus.EXPIRED}.issubset(statuses):
        return [
            f"Merged job {job_id}: conflicting freshness_status values across sources; "
            "expiry_at takes precedence, otherwise expired wins."
        ]
    return []


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

        warnings.extend(_record_quality_warnings(raw, label, reference_now))

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

        documents: dict[str, SourceDocument] = {}
        for raw in records:
            for document in _source_documents(raw):
                documents.setdefault(document.document_id, document)
        source_documents = sorted(documents.values(), key=lambda document: document.document_id)
        preferred = min(
            source_documents,
            key=lambda document: (
                document.is_excerpt or not document.text.strip(),
                document.document_id,
            ),
            default=None,
        )
        directions = _dedupe_keep_order(
            [
                direction
                for raw in records
                for direction in [
                    _clean_text(raw.get("target_direction")),
                    *_clean_str_list(raw.get("target_directions")),
                ]
                if direction
            ]
        )
        employment_types = _dedupe_keep_order(
            [employment for raw in records if (employment := _raw_employment_type(raw))]
        )
        if len(employment_types) > 1:
            warnings.append(
                "Conflicting source employment types; merged employment type left unknown."
            )

        job_id = _clean_text(first.get("job_id"))
        if job_id is None:
            job_id = "gen-" + sha256("|".join(key).encode("utf-8")).hexdigest()[:16]

        warnings.extend(_status_conflict_warnings(job_id, groups[key].raw_statuses))

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
                target_directions=directions,
                source_documents=source_documents,
                description=(_clean_description(preferred.text) or "") if preferred else "",
                description_is_excerpt=preferred.is_excerpt if preferred else True,
                employment_type=employment_types[0] if len(employment_types) == 1 else None,
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


def _raw_employment_type(raw: dict[str, Any]) -> str | None:
    value = _clean_text(raw.get("employment_type"))
    if value:
        return value
    payload = raw.get("raw_payload")
    if not isinstance(payload, dict):
        return None
    labels = (
        payload.get("employment_type")
        or payload.get("job_type")
        or payload.get("workType")
        or payload.get("workTypes")
        or payload.get("job_types")
    )
    values = [labels] if isinstance(labels, str) else labels if isinstance(labels, list) else []
    aliases = {
        "full-time": {"full time", "fulltime", "全职", "全職"},
        "part-time": {"part time", "parttime", "兼职", "兼職"},
        "internship": {"intern", "internship", "实习", "實習"},
        "contract": {"contract", "contract/temp", "合同工"},
        "freelance": {"freelance", "自由职业"},
    }
    for label in values:
        if isinstance(label, str):
            normalized_label = " ".join(
                label.casefold().replace("_", " ").replace("-", " ").split()
            )
            for kind, names in aliases.items():
                if normalized_label in names:
                    return kind
    return None


def _source_documents(raw: dict[str, Any]) -> list[SourceDocument]:
    existing = raw.get("source_documents")
    documents: list[SourceDocument] = []
    if isinstance(existing, list):
        for value in existing:
            try:
                documents.append(SourceDocument.model_validate(value))
            except ValidationError:
                continue
    if documents:
        return documents
    text = raw.get("description")
    fetched_at = _parse_datetime(raw.get("fetched_at"))
    if not isinstance(text, str) or not text.strip() or fetched_at is None:
        return []
    payload = raw.get("raw_payload")
    payload = payload if isinstance(payload, dict) else {}
    fetched_at = _parse_datetime(payload.get("detail_fetched_at")) or fetched_at
    is_excerpt = bool(raw.get("description_is_excerpt") or payload.get("description_is_excerpt"))
    source = _clean_text(raw.get("source")) or "unknown"
    url = _clean_text(raw.get("source_url")) or ""
    versions = [(text, fetched_at, is_excerpt)]
    listing_text = payload.get("listing_description")
    listing_stamp = _parse_datetime(payload.get("listing_fetched_at"))
    if isinstance(listing_text, str) and listing_text.strip() and listing_stamp:
        versions.append((listing_text, listing_stamp, True))
    for document_text, stamp, excerpt in versions:
        identity = "\0".join((source, url, document_text, stamp.isoformat(), str(excerpt)))
        documents.append(
            SourceDocument(
                document_id="jd-" + sha256(identity.encode("utf-8")).hexdigest()[:24],
                source=source,
                source_url=url,
                text=document_text,
                fetched_at=stamp,
                is_excerpt=excerpt,
            )
        )
    return documents


def select_balanced_candidates(jobs: Sequence[JobPosting], limit: int = 20) -> list[JobPosting]:
    """Rotate directions, then sources; each stable vacancy ID consumes one slot."""
    if limit <= 0:
        return []
    groups: dict[str, dict[str, deque[JobPosting]]] = defaultdict(lambda: defaultdict(deque))
    ordered = sorted(
        jobs,
        key=lambda job: (
            not any(
                document.text.strip() and not document.is_excerpt
                for document in job.source_documents
            )
            if job.source_documents
            else not bool(job.description.strip() and not job.description_is_excerpt),
            job.job_id,
            job.source_url,
        ),
    )
    for job in ordered:
        if job.freshness_status == FreshnessStatus.EXPIRED:
            continue
        directions = set(job.target_directions or [job.target_direction])
        sources = {document.source for document in job.source_documents} or set(
            job.source.split(", ")
        )
        for direction in sorted(directions):
            for source in sorted(sources):
                groups[direction][source].append(job)
    source_rotation = {direction: deque(sorted(sources)) for direction, sources in groups.items()}
    directions_left = deque(sorted(groups))
    selected: list[JobPosting] = []
    seen: set[str] = set()
    while directions_left and len(selected) < limit:
        direction = directions_left.popleft()
        rotation = source_rotation[direction]
        while rotation:
            source = rotation.popleft()
            queue = groups[direction][source]
            while queue and queue[0].job_id in seen:
                queue.popleft()
            if not queue:
                continue
            job = queue.popleft()
            seen.add(job.job_id)
            selected.append(job)
            if queue:
                rotation.append(source)
            break
        if rotation:
            directions_left.append(direction)
    return selected
