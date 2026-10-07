"""Class-code registration and username/password authentication."""

import secrets
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tortoise.exceptions import IntegrityError

from jobscout.models import LoginSession, User
from jobscout.services.auth_service import PASSWORD_HASHER, AuthService, Identity, auth_error

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class Registration(Credentials):
    registration_code: str = Field(min_length=1, max_length=256, repr=False)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=12, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


def service(request: Request) -> AuthService:
    return request.app.state.auth  # type: ignore[no-any-return]


def cookie_name(auth: AuthService) -> str:
    return "__Host-jobscout_session" if auth.settings.cookie_secure else "jobscout_session"


async def login_response(auth: AuthService, response: Response, user: User) -> dict[str, object]:
    token, session = await auth.issue(user)
    response.set_cookie(
        cookie_name(auth),
        token,
        max_age=43200,
        httponly=True,
        secure=auth.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return auth.public(user, session)


@router.post("/register", status_code=201)
async def register(
    request: Request, response: Response, payload: Registration
) -> dict[str, object]:
    auth = service(request)
    ip = request.client.host if request.client else "unknown"
    limits = [(f"register:{ip}", 60)]
    auth.check_rate(limits)
    auth.failed(limits)
    expected = auth.settings.registration_code.get_secret_value()
    if not expected or not secrets.compare_digest(
        payload.registration_code.encode(), expected.encode()
    ):
        raise auth_error(403, "invalid_registration_code")
    hashed = await auth.hash_password(payload.password)
    try:
        user = await User.create(
            user_id=str(uuid4()), username=payload.username, password_hash=hashed
        )
    except IntegrityError:
        raise auth_error(409, "username_unavailable") from None
    return await login_response(auth, response, user)


@router.post("/login")
async def login(request: Request, response: Response, payload: Credentials) -> dict[str, object]:
    auth = service(request)
    ip = request.client.host if request.client else "unknown"
    limits = [(f"username:{payload.username}", 10), (f"login:{ip}", 60)]
    attempt = auth.reserve_attempt(limits)
    user = await User.get_or_none(username=payload.username)
    if user is None:
        await auth.verify(auth.dummy_hash, payload.password)
        raise auth_error(401, "invalid_credentials")
    async with auth.user_lock(user.user_id):
        await user.refresh_from_db()
        if not await auth.verify(user.password_hash, payload.password):
            raise auth_error(401, "invalid_credentials")
        if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
            user.password_hash = await auth.hash_password(payload.password)
            await user.save(update_fields=["password_hash"])
        result = await login_response(auth, response, user)
        auth.release_attempt(limits, attempt)
        return result


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    identity: Identity = request.state.identity
    return service(request).public(identity.user, identity.session)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    auth = service(request)
    identity: Identity = request.state.identity
    await auth.revoke(token=identity.session.token_hash)
    response.delete_cookie(
        cookie_name(auth),
        path="/",
        secure=auth.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/password", status_code=204)
async def change_password(request: Request, payload: PasswordChange, response: Response) -> None:
    auth = service(request)
    identity: Identity = request.state.identity
    limits = [(f"password:{identity.user.user_id}", 10)]
    attempt = auth.reserve_attempt(limits)
    async with auth.user_lock(identity.user.user_id):
        if not await LoginSession.filter(token_hash=identity.session.token_hash).exists():
            raise auth_error(401, "authentication_required")
        await identity.user.refresh_from_db()
        if not await auth.verify(identity.user.password_hash, payload.current_password):
            raise auth_error(401, "invalid_credentials")
        identity.user.password_hash = await auth.hash_password(payload.new_password)
        await identity.user.save(update_fields=["password_hash"])
        await auth.revoke(user_id=identity.user.user_id)
        auth.release_attempt(limits, attempt)
    response.delete_cookie(
        cookie_name(auth),
        path="/",
        secure=auth.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
