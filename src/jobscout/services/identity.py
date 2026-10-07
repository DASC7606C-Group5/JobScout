"""Authenticated account identity, inherited by its background tasks."""

from contextvars import ContextVar

current_user_id: ContextVar[str] = ContextVar("current_user_id")


def owner_id() -> str:
    return current_user_id.get()
