"""Same-origin API access and account identity without buffering event streams."""

import secrets
from typing import cast

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from jobscout.api.auth import cookie_name
from jobscout.services.auth_service import AuthService, auth_error
from jobscout.services.identity import current_user_id


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
        try:
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

            async def secure_send(message: object) -> None:
                if isinstance(message, dict) and message.get("type") == "http.response.start":
                    message.setdefault("headers", []).extend(
                        [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
                    )
                await send(message)  # type: ignore[arg-type]

            await self.app(scope, receive, secure_send)
        except HTTPException as error:
            await JSONResponse(
                {"detail": error.detail},
                status_code=error.status_code,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
        finally:
            if identity:
                auth.unlisten(identity)
            if token is not None:
                current_user_id.reset(token)
