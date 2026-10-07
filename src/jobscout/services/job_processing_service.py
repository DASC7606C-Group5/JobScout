"""Normalize raw jobs, deduplicate postings, and classify freshness.

It converts raw retrieval records into ``JobPosting`` objects,
retains source-specific documents and all matched directions,
merges cross-source duplicates while preserving every source link, and marks
each posting as ``active`` / ``expired`` / ``unknown``. Freshness is never
guessed: without explicit source data a posting stays ``unknown``.

Missing fields are handled as follows:

- records missing any required field (``title``, ``company``,
  ``source_url``, ``target_direction``, ``fetched_at``) are
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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, NamedTuple

from pydantic import ValidationError
from selectolax.lexbor import LexborHTMLParser

from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument
from jobscout.services.job_retrieval.employment import source_employment_label

# Text fields JobPosting requires; a raw record missing
# any of them is dropped with a warning. ``fetched_at`` is also required but
# validated separately because it must parse as a datetime.
_REQUIRED_TEXT_FIELDS = ("title", "company", "source_url", "target_direction")


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


def _html_description_text(value: str) -> str:
    if not re.search(r"</?[a-zA-Z][^>]*>", value):
        return value
    tree = LexborHTMLParser(value)
    tree.strip_tags(["script", "style"])
    for node in tree.css(",".join(_HTML_BLOCK_TAGS)):
        node.insert_before("\n")
        node.insert_after("\n")
    return re.sub(r"\n\s*\n", "\n", tree.text())


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
    return " ".join(normalized.casefold().split())


def _parse_responsibilities(raw: dict[str, Any], description: str | None) -> list[str]:
    """Keep the source's fields; the assessment model reads the full job description later."""
    return _dedupe_keep_order(_clean_str_list(raw.get("responsibilities")))


def _parse_required_skills(raw: dict[str, Any], description: str | None) -> list[str]:
    return _dedupe_keep_order(_clean_str_list(raw.get("required_skills")))


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
    """Decide freshness from source data only; never guess ``active``.

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

    Records missing a required field (``title``, ``company``,
    ``source_url``, ``target_direction`` or a parseable
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
        key = (
            _dedup_key_part(company),
            _dedup_key_part(title),
            _dedup_key_part(location) if location else str(raw.get("source_url", "")),
        )
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
        return source_employment_label(value)
    payload = raw.get("raw_payload")
    if not isinstance(payload, dict):
        return None
    values: list[object] = []
    for field_name in ("employment_type", "job_type", "workType", "workTypes", "job_types"):
        label = payload.get(field_name)
        values.extend(label if isinstance(label, list) else [label])
    return source_employment_label(values)


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


def select_candidates(jobs: Sequence[JobPosting], limit: int = 20) -> list[JobPosting]:
    """Choose distinct readable candidates without source or direction quotas."""
    ordered = sorted(
        jobs,
        key=lambda job: (
            not bool(job.description.strip() and not job.description_is_excerpt),
            job.job_id,
            job.source_url,
        ),
    )
    selected: dict[str, JobPosting] = {}
    for job in ordered:
        if len(selected) >= max(0, limit):
            break
        if job.freshness_status != FreshnessStatus.EXPIRED:
            selected.setdefault(job.job_id, job)
    return list(selected.values())
