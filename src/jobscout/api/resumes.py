"""Bounded multipart ingestion and document extraction."""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from jobscout.config import get_settings
from jobscout.schemas.session import ResumeInput
from jobscout.services.resume_service import ResumeParseError, parse_resume, validate_resume_name

router = APIRouter(prefix="/api/v1/resumes", tags=["resume"])


class ResumeLimits(BaseModel):
    max_bytes: int
    max_pdf_pages: int
    max_text_characters: int


@router.get("/limits", response_model=ResumeLimits)
async def resume_limits() -> ResumeLimits:
    settings = get_settings()
    return ResumeLimits(
        max_bytes=settings.resume_max_bytes,
        max_pdf_pages=settings.resume_max_pdf_pages,
        max_text_characters=settings.resume_max_text_characters,
    )


@router.post(
    "/parse",
    response_model=ResumeInput,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        },
    },
)
async def parse_resume_upload(request: Request) -> ResumeInput:
    settings = get_settings()
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise HTTPException(422, {"code": "invalid_input"})
    try:
        parser = MultiPartParser(request.headers, request.stream(), max_files=1, max_fields=0)
        try:
            form = await parser.parse()
        except BaseException:
            # Starlette closes partial files for malformed multipart data only. A
            # disconnected or cancelled request must release the same spool files.
            for temporary_file in parser._files_to_close_on_error:
                temporary_file.close()
            raise
        try:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise HTTPException(422, {"code": "invalid_input"})
            validate_resume_name(file.filename)
            if file.size is not None and file.size > settings.resume_max_bytes:
                raise ResumeParseError(
                    "file_too_large", "The file exceeds the upload size limit.", 413
                )
            async with request.app.state.resume_slots:
                content = await file.read(settings.resume_max_bytes + 1)
                work = asyncio.create_task(run_in_threadpool(parse_resume, file.filename, content))
                try:
                    return await asyncio.shield(work)
                except asyncio.CancelledError:
                    # A parser thread cannot be cancelled; retain its slot until it ends.
                    while not work.done():
                        try:
                            await asyncio.shield(work)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                    if not work.cancelled():
                        work.exception()
                    raise
        finally:
            await form.close()
    except ResumeParseError as error:
        raise HTTPException(
            error.status_code,
            {"code": error.code, "message": str(error), "action": "edit_conditions"},
        ) from error
    except MultiPartException:
        if getattr(request.state, "upload_timed_out", False):
            raise HTTPException(408, {"code": "upload_timeout"}) from None
        if getattr(request.state, "upload_too_large", False):
            raise HTTPException(413, {"code": "request_too_large"}) from None
        raise HTTPException(400, {"code": "invalid_input"}) from None
