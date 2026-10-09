"""Same-origin API access and account identity without buffering event streams."""

import asyncio
import secrets
from typing import cast

from fastapi import HTTPException, Request
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from jobscout.api.auth import cookie_name
from jobscout.config import get_settings
from jobscout.services.auth_service import AuthService, auth_error
from jobscout.services.identity import current_user_id

MAX_API_BODY_BYTES = 1024 * 1024
MAX_AUTH_BODY_BYTES = 16 * 1024


def request_body_limit(path: str) -> int:
    if path == "/api/v1/resumes/parse":
        return get_settings().resume_max_bytes + 64 * 1024
    if path.startswith("/api/v1/auth/"):
        return MAX_AUTH_BODY_BYTES
    return MAX_API_BODY_BYTES


def request_too_large() -> HTTPException:
    return HTTPException(
        413,
        {
            "code": "request_too_large",
            "message": "The request is too large. Shorten the text or upload a smaller file.",
            "action": "edit_conditions",
        },
    )


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        auth = cast(AuthService, request.app.state.auth)
        token = None
        identity = None
        upload_reserved = False
        upload_deadline = 0.0
        try:
            body_limit = request_body_limit(scope["path"])
            content_length = request.headers.get("content-length")
            if content_length is not None:
                if not content_length.isascii() or not content_length.isdecimal():
                    raise auth_error(400, "invalid_content_length")
                # Compare decimal strings before converting untrusted, arbitrarily long input.
                size = content_length.lstrip("0") or "0"
                if len(size) > len(str(body_limit)) or int(size) > body_limit:
                    raise request_too_large()
            public = scope["path"] in {
                "/api/v1/health",
                "/api/v1/auth/login",
                "/api/v1/auth/register",
            }
            if not public:
                identity = await auth.authenticate(request.cookies.get(cookie_name(auth), ""))
                request.state.identity = identity
                token = current_user_id.set(identity.user.user_id)
            if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("origin") != auth.settings.public_origin.rstrip("/"):
                    raise auth_error(403, "invalid_origin")
                if identity and not secrets.compare_digest(
                    request.headers.get("x-csrf-token", "").encode(),
                    identity.session.csrf_token.encode(),
                ):
                    raise auth_error(403, "invalid_csrf_token")

            received_bytes = 0
            if scope["path"] == "/api/v1/resumes/parse" and scope["method"] == "POST":
                if request.app.state.upload_slots.locked():
                    raise HTTPException(
                        429, {"code": "upload_capacity"}, headers={"Retry-After": "10"}
                    )
                await request.app.state.upload_slots.acquire()
                upload_reserved = True
                upload_deadline = (
                    asyncio.get_running_loop().time() + auth.settings.upload_timeout_seconds
                )

            async def limited_receive() -> Message:
                nonlocal received_bytes
                if upload_reserved:
                    try:
                        async with asyncio.timeout_at(upload_deadline):
                            message = await receive()
                    except TimeoutError:
                        request.state.upload_timed_out = True
                        raise MultiPartException("Upload timed out.") from None
                else:
                    message = await receive()
                if message["type"] == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > body_limit:
                        if upload_reserved:
                            request.state.upload_too_large = True
                            raise MultiPartException("Upload is too large.")
                        raise request_too_large()
                return message

            async def secure_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    message.setdefault("headers", []).extend(
                        [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
                    )
                await send(message)

            if identity and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                # A write authenticated before account deletion must not recreate private data.
                async with auth.write_lock(identity.user.user_id):
                    await auth.identity(request.cookies.get(cookie_name(auth), ""))
                    await self.app(scope, limited_receive, secure_send)
            else:
                await self.app(scope, limited_receive, secure_send)
        except HTTPException as error:
            await JSONResponse(
                {"detail": error.detail},
                status_code=error.status_code,
                headers={"Cache-Control": "no-store", **(error.headers or {})},
            )(scope, receive, send)
        finally:
            if upload_reserved:
                request.app.state.upload_slots.release()
            if identity:
                auth.unlisten(identity)
            if token is not None:
                current_user_id.reset(token)
