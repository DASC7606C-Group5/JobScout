"""Build applicant notices and recovery actions from search and job results."""

from collections.abc import Iterable, Sequence
from typing import Literal

from jobscout.schemas.errors import ApplicantError
from jobscout.schemas.job import FreshnessStatus
from jobscout.schemas.notices import ApplicantNotice, NoticeCode
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.services.job_retrieval.models import SourceOutcome

_PREFERENCES = {
    "salary_range": "salary",
    "work_mode": "work arrangement",
    "industry": "industry",
    "location": "work location",
    "employment_type": "employment type",
    "target_direction": "type of job",
}
_SOURCES = {
    "jobsdb": "JobsDB",
    "liepin": "Liepin",
    "zhaopin": "Zhaopin",
    "shixiseng": "Shixiseng",
    "remotive": "Remotive",
    "arbeitnow": "Arbeitnow",
    "careerjet": "Careerjet",
    "careerjet_hk": "Careerjet",
    "careerjet_cn": "Careerjet",
}


def source_label(source: str | None) -> str:
    return _SOURCES.get(source or "", "A job source")


def make_notice(
    code: NoticeCode,
    *,
    job_id: str | None = None,
    source: str | None = None,
    preference: str | None = None,
    job_title: str | None = None,
) -> ApplicantNotice:
    """Only trusted templates supply copy; references never become diagnostic prose."""
    if code == "preference_unverified" and not job_id:
        raise ValueError("preference_unverified_requires_job")
    title = f"“{job_title}”" if job_title else "This role"
    source_name = source_label(source)
    preference_name = _PREFERENCES.get(preference or "", "search criteria")
    messages: dict[NoticeCode, str] = {
        "source_unavailable": f"{source_name} was unavailable, so these results cover fewer openings.",
        "source_partial": f"Only some listings from {source_name} were available.",
        "coverage_limited": "These results cover a selection of openings. Change your search criteria to explore other roles.",
        "listing_incomplete": f"Only a summary is available for {title}. See the full listing for details.",
        "listing_status_unverified": f"Check whether applications for {title} are still open.",
        "preference_unverified": f"Confirm the {preference_name} for {title} before applying.",
        "analysis_partial": f"The match review for {title} covers only some requirements.",
        "analysis_unavailable": f"A personal match review for {title} is unavailable. You can still view the listing.",
    }
    action: Literal["retry", "edit_conditions", "open_listing"] | None
    action = "open_listing" if job_id else "edit_conditions" if code == "coverage_limited" else None
    return ApplicantNotice(
        code=code,
        scope="job" if job_id else "source" if source else "session",
        message=messages[code],
        action=action,
        job_id=job_id,
        source=source,
        preference=preference,
    )


def dedupe_notices(notices: Iterable[ApplicantNotice]) -> list[ApplicantNotice]:
    unique: dict[tuple[str, str, str | None, str | None, str | None], ApplicantNotice] = {}
    for notice in notices:
        key = (notice.code, notice.scope, notice.job_id, notice.source, notice.preference)
        unique.setdefault(key, notice)
    return list(unique.values())


def source_notices(outcomes: Iterable[SourceOutcome]) -> list[ApplicantNotice]:
    statuses: dict[str, set[str]] = {}
    for outcome in outcomes:
        statuses.setdefault(outcome.source, set()).add(outcome.status)
    notices: list[ApplicantNotice] = []
    for source, seen in statuses.items():
        if seen & {"partial", "blocked", "unavailable"}:
            code: NoticeCode = (
                "source_partial" if seen & {"ok", "partial", "empty"} else "source_unavailable"
            )
            notices.append(make_notice(code, source=source))
    return notices


def finalize_recommendation(
    result: RecommendationResult,
    *,
    notices: Sequence[ApplicantNotice] = (),
) -> RecommendationResult:
    """Attach notices only to final selected, merged jobs, without changing ordering."""
    incoming = dedupe_notices([*result.notices, *notices])
    global_notices = [
        notice
        for notice in incoming
        if not notice.job_id and notice.code != "preference_unverified"
    ]
    items = []
    for item in [*result.jobs, *result.pending_jobs]:
        job = item.job
        values = dedupe_notices(
            [*item.notices, *(notice for notice in incoming if notice.job_id == job.job_id)]
        )
        values = [notice for notice in values if notice.job_id == job.job_id]
        # A complete mirror takes precedence over an excerpt from another source.
        complete_description = job.has_full_description()
        derived_codes = {
            "listing_incomplete",
            "listing_status_unverified",
            "analysis_partial",
            "analysis_unavailable",
            "preference_unverified",
        }
        values = [notice for notice in values if notice.code not in derived_codes]
        if not complete_description:
            values.append(make_notice("listing_incomplete", job_id=job.job_id))
        if job.freshness_status == FreshnessStatus.UNKNOWN:
            values.append(make_notice("listing_status_unverified", job_id=job.job_id))
        if item.analysis_status == "unavailable" or (
            item.analysis_status == "partial"
            and (complete_description or item.review_issue is not None)
        ):
            values.append(
                make_notice(
                    "analysis_partial"
                    if item.analysis_status == "partial"
                    else "analysis_unavailable",
                    job_id=job.job_id,
                )
            )
        if item.verification_status != "confirmed":
            unknown = item.unknown_conditions
            if not unknown and item.analysis_status == "complete":
                unknown = ["search"]
            for field in unknown:
                values.append(
                    make_notice("preference_unverified", job_id=job.job_id, preference=field)
                )
        values = dedupe_notices(
            make_notice(
                notice.code,
                job_id=job.job_id,
                source=notice.source,
                preference=notice.preference,
                job_title=job.title,
            )
            for notice in values
        )
        items.append(item.model_copy(update={"notices": values}))
    return result.model_copy(
        update={
            "jobs": items[: len(result.jobs)],
            "pending_jobs": items[len(result.jobs) :],
            "notices": dedupe_notices(global_notices),
        }
    )


_ERRORS: dict[str, tuple[str, str | None]] = {
    "queue_full": ("The waiting list is full. Try again shortly.", "retry"),
    "queue_expired": (
        "The waiting period ended. Your input is saved; join the queue again.",
        "retry",
    ),
    "queue_cancelled": ("The queued operation was cancelled. Your input is saved.", "retry"),
    "operation_already_started": (
        "The operation has already started or finished. Reload for its status.",
        "reload",
    ),
    "model_unavailable": (
        "The model request failed. Your input is saved. Check Settings or retry.",
        "retry",
    ),
    "search_unavailable": (
        "Job sources are temporarily unavailable. Your input is saved; try again later.",
        "retry",
    ),
    "service_unavailable": (
        "JobScout is temporarily unavailable. Your input is saved; try again later.",
        "retry",
    ),
    "search_timeout": ("The search took too long. Your input is saved; try again.", "retry"),
    "analysis_unavailable": (
        "Your search could not finish. Your input is saved; try again.",
        "retry",
    ),
    "invalid_input": ("Check the information you entered and try again.", "edit_conditions"),
    "resume_consent_required": (
        "Confirm that you consent to sending your resume to the configured AI model.",
        "edit_conditions",
    ),
    "invalid_answer": ("Check your answer or update your search criteria.", "edit_conditions"),
    "search_changed": ("Your search has changed. Reload it before continuing.", "reload"),
    "draft_conflict": ("The shared draft has changed. Reload it before saving.", "reload"),
    "search_interrupted": (
        "Your search was interrupted. Your input is saved; retry when ready.",
        "retry",
    ),
    "saved_job_not_found": (
        "This recommendation is no longer available. Reload the search.",
        "reload",
    ),
    "operation_in_progress": (
        "Your search is still working. Reload it to see the latest progress.",
        "reload",
    ),
    "request_conflict": (
        "This update could not be applied. Reload your search and try again.",
        "reload",
    ),
    "search_completed": ("Update your criteria to start another search.", "edit_conditions"),
    "search_not_found": (
        "This search is no longer available. Start a new search.",
        "start_new_search",
    ),
    "search_not_retryable": ("Update your criteria or start a new search.", "edit_conditions"),
}


def public_error(code: str, *, retryable: bool = True) -> ApplicantError:
    code = {
        "model_auth": "model_unavailable",
        "model_configuration": "model_unavailable",
        "model_http": "model_unavailable",
        "model_output": "model_unavailable",
        "model_transport": "model_unavailable",
        "model_timeout": "model_unavailable",
        "operation_timeout": "search_timeout",
        "profile_input": "invalid_input",
    }.get(code, code)
    if code not in _ERRORS:
        code = "analysis_unavailable"
    message, action = _ERRORS[code]
    if action == "retry" and not retryable:
        action = "edit_conditions"
    return ApplicantError.model_validate({"code": code, "message": message, "action": action})
