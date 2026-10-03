from copy import deepcopy
from typing import Literal, TypedDict, TypeGuard

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.services import job_processing_service

type RawJobs = list[dict[str, object]]
type JobProcessingResult = tuple[list[JobPosting], list[str]]


class JobProcessingUpdate(TypedDict):
    normalized_jobs: list[JobPosting]
    warnings: list[str]
    errors: list[WorkflowError]
    current_stage: Literal["process_jobs", "failed"]
    recommendation: None


def process_jobs_node(state: AgentState) -> JobProcessingUpdate:
    if "raw_jobs" not in state:
        return _failure("RAW_JOBS_MISSING", "Job processing requires raw_jobs.")

    raw_jobs: object = state["raw_jobs"]
    if not _is_raw_jobs(raw_jobs):
        return _failure(
            "RAW_JOBS_INVALID", "raw_jobs must be a list of dictionaries with string keys."
        )

    if not raw_jobs:
        return _base_update()

    process_jobs: object = getattr(job_processing_service, "process_jobs", None)
    if not callable(process_jobs):
        return _failure(
            "JOB_PROCESSING_SERVICE_UNAVAILABLE",
            "job_processing_service must provide a callable process_jobs(raw_jobs).",
        )

    try:
        result: object = process_jobs(deepcopy(raw_jobs))
    except Exception as error:
        return _failure("JOB_PROCESSING_FAILED", f"Job processing failed: {error}")

    if not _is_processing_result(result):
        return _failure(
            "JOB_PROCESSING_RESULT_INVALID",
            "The job processing service must return (a list of JobPostings, a list of warnings as strings)",
        )

    jobs, warnings = result
    update = _base_update()
    update["normalized_jobs"] = jobs
    update["warnings"] = list(dict.fromkeys(warnings))
    return update


def _base_update() -> JobProcessingUpdate:
    return {
        "normalized_jobs": [],
        "warnings": [],
        "errors": [],
        "current_stage": "process_jobs",
        "recommendation": None,
    }


def _failure(code: str, message: str) -> JobProcessingUpdate:
    update = _base_update()
    update["current_stage"] = "failed"
    update["errors"].append(WorkflowError(code=code, message=message, stage="process_jobs"))
    return update


def _is_raw_jobs(value: object) -> TypeGuard[RawJobs]:
    if not isinstance(value, list):
        return False
    return all(
        isinstance(item, dict) and all(isinstance(key, str) for key in item) for item in value
    )


def _is_processing_result(value: object) -> TypeGuard[JobProcessingResult]:
    if not isinstance(value, tuple) or len(value) != 2:
        return False
    jobs, warnings = value
    return (
        isinstance(jobs, list)
        and all(isinstance(job, JobPosting) for job in jobs)
        and isinstance(warnings, list)
        and all(isinstance(warning, str) for warning in warnings)
    )
