"""Existing workflow tests use a real authenticated account, including CSRF."""

from typing import Self

from fastapi.testclient import TestClient

from jobscout.config import get_settings


class AuthenticatedClient(TestClient):
    def __enter__(self) -> Self:
        super().__enter__()
        if not hasattr(getattr(self.app, "state", None), "auth"):
            return self
        self.headers["Origin"] = get_settings().public_origin
        credentials = {"username": "workflow", "password": "synthetic-password-123"}
        result = self.post(
            "/api/v1/auth/register",
            json={**credentials, "registration_code": "synthetic-class-code"},
        )
        if result.status_code == 409:
            result = self.post("/api/v1/auth/login", json=credentials)
        assert result.status_code in {200, 201}, result.text
        self.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        return self
