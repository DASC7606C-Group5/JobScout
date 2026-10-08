"""Password verification and revocable, server-owned login sessions."""

import asyncio
import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakValueDictionary

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cachetools import TTLCache
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from jobscout.config import Settings
from jobscout.models import LoginSession, User

PASSWORD_HASHER = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=1)
AUTH_RATE_WINDOW_SECONDS = 900
MAX_AUTH_RATE_KEYS = 10_000


def auth_error(status: int, code: str) -> HTTPException:
    return HTTPException(status, {"code": code})


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Identity:
    user: User
    session: LoginSession
    revoked: asyncio.Event = field(default_factory=asyncio.Event)


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.hash_slots = asyncio.Semaphore(2)
        self.failures: TTLCache[str, deque[float]] = TTLCache(
            maxsize=MAX_AUTH_RATE_KEYS, ttl=AUTH_RATE_WINDOW_SECONDS
        )
        self.user_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self.session_lock = asyncio.Lock()
        self.listeners: dict[str, list[Identity]] = {}
        self.dummy_hash: str = ""

    async def open(self) -> None:
        await LoginSession.filter(expires_at__lte=datetime.now(UTC)).delete()

    async def dummy_password_hash(self) -> str:
        if not self.dummy_hash:
            self.dummy_hash = await self.hash_password(secrets.token_urlsafe(32))
        return self.dummy_hash

    async def hash_password(self, password: str) -> str:
        async with self.hash_slots:
            return await run_in_threadpool(PASSWORD_HASHER.hash, password)

    async def verify(self, hashed: str, password: str) -> bool:
        async with self.hash_slots:
            try:
                return await run_in_threadpool(PASSWORD_HASHER.verify, hashed, password)
            except VerificationError:
                return False

    def check_rate(self, keys: list[tuple[str, int]]) -> None:
        now = time.monotonic()
        for key, limit in keys:
            failures = self.failures.get(key, deque())
            while failures and failures[0] <= now - AUTH_RATE_WINDOW_SECONDS:
                failures.popleft()
            if len(failures) >= limit:
                raise auth_error(429, "auth_rate_limited")
        # Reject new keys at capacity instead of evicting an active account's limit.
        missing = {key for key, _ in keys if key not in self.failures}
        if len(self.failures) + len(missing) > self.failures.maxsize:
            raise auth_error(429, "auth_rate_limited")

    def reserve_attempt(self, keys: list[tuple[str, int]]) -> float:
        self.check_rate(keys)
        attempt = time.monotonic()
        for key, _ in keys:
            entries = self.failures.get(key, deque())
            entries.append(attempt)
            self.failures[key] = entries
        return attempt

    def release_attempt(self, keys: list[tuple[str, int]], attempt: float) -> None:
        for key, _ in keys:
            entries = self.failures.get(key, deque())
            if attempt in entries:
                entries.remove(attempt)
                if not entries:
                    self.failures.pop(key, None)

    def user_lock(self, user_id: str) -> asyncio.Lock:
        return self.user_locks.setdefault(user_id, asyncio.Lock())

    async def issue(self, user: User) -> tuple[str, LoginSession]:
        token = secrets.token_urlsafe(32)
        session = await LoginSession.create(
            token_hash=token_hash(token),
            owner_id=user.user_id,
            csrf_token=secrets.token_hex(32),
            expires_at=datetime.now(UTC) + timedelta(hours=12),
        )
        return token, session

    async def identity(self, token: str) -> Identity:
        session = await LoginSession.get_or_none(token_hash=token_hash(token))
        if session is None or session.expires_at <= datetime.now(UTC):
            raise auth_error(401, "authentication_required")
        user = await User.get_or_none(user_id=session.owner_id)
        if user is None:
            raise auth_error(401, "authentication_required")
        return Identity(user, session)

    async def authenticate(self, token: str) -> Identity:
        async with self.session_lock:
            identity = await self.identity(token)
            self.listen(identity)
            return identity

    def listen(self, identity: Identity) -> None:
        self.listeners.setdefault(identity.session.token_hash, []).append(identity)

    def unlisten(self, identity: Identity) -> None:
        entries = self.listeners.get(identity.session.token_hash, [])
        if identity in entries:
            entries.remove(identity)
        if not entries:
            self.listeners.pop(identity.session.token_hash, None)

    async def revoke(self, *, token: str | None = None, user_id: str | None = None) -> None:
        async with self.session_lock:
            query = (
                LoginSession.filter(owner_id=user_id)
                if user_id
                else LoginSession.filter(token_hash=token)
            )
            hashes = await query.values_list("token_hash", flat=True)
            await query.delete()
            for hashed in hashes:
                for identity in self.listeners.pop(str(hashed), []):
                    identity.revoked.set()

    @staticmethod
    def public(user: User, session: LoginSession) -> dict[str, Any]:
        return {
            "user_id": user.user_id,
            "username": user.username,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at.isoformat(),
        }
