"""File ingestion kept separate from session creation and workflow execution."""

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from jobscout.schemas.session import ResumeInput
from jobscout.services.resume_service import (
    MAX_RESUME_BYTES,
    ResumeParseError,
    parse_resume,
    validate_resume_name,
)

router = APIRouter(prefix="/api/v1/resumes", tags=["resume"])


@router.post("/parse", response_model=ResumeInput)
async def parse_resume_upload(file: UploadFile) -> ResumeInput:
    try:
        validate_resume_name(file.filename)
        if file.size is not None and file.size > MAX_RESUME_BYTES:
            raise ResumeParseError(
                "file_too_large", "The file is too large. Choose a resume under 10 MB.", 413
            )
        content = await file.read(MAX_RESUME_BYTES + 1)
        return await run_in_threadpool(parse_resume, file.filename, content)
    except ResumeParseError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error), "action": "edit_conditions"},
        ) from error
    finally:
        await file.close()
