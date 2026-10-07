"""Per-account model credentials and atomic server-operation allowances."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from jobscout.config import Settings
from jobscout.models import DailyUsage, PersonalModel
from jobscout.services.auth_service import auth_error
from jobscout.services.llm_service import ModelRouter, get_llm_provider

type Role = Literal["semantic", "decision"]
ROLES: tuple[Role, ...] = ("semantic", "decision")


class ModelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    thinking: bool = False
    thinking_level: str = Field(default="high", min_length=1, max_length=32)


@dataclass
class OperationModels:
    provider: ModelRouter
    uses_server: bool


class ModelSettingsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cipher = (
            Fernet(settings.credentials_key.get_secret_value().encode())
            if settings.credentials_key.get_secret_value()
            else None
        )
        self.endpoints = {
            "deepseek": {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "provider": "deepseek",
            },
            "openai": {
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "provider": "openai",
            },
            **settings.model_endpoints,
        }
        for endpoint in self.endpoints.values():
            url = httpx.URL(endpoint["base_url"])
            if (
                url.scheme != "https"
                or not url.host
                or url.userinfo
                or url.query
                or url.fragment
                or endpoint.get("provider") not in {"deepseek", "openai", "openai_compatible"}
            ):
                raise ValueError("Model endpoints must use HTTPS and a supported provider.")

    async def read(self, owner: str) -> dict[str, Any]:
        records = {row.role: row for row in await PersonalModel.filter(owner_id=owner)}
        roles: dict[str, Any] = {}
        for role in ROLES:
            row = records.get(role)
            roles[role] = {
                "personal": row is not None,
                "endpoint_id": row.endpoint_id if row else None,
                "model": row.model if row else getattr(self.settings, f"llm_{role}_model"),
                "key_configured": bool(row)
                if row
                else bool(getattr(self.settings, f"llm_{role}_api_key")),
                "server_provider": getattr(self.settings, f"llm_{role}_provider"),
                "server_model": getattr(self.settings, f"llm_{role}_model"),
                "server_key_configured": bool(getattr(self.settings, f"llm_{role}_api_key")),
                "thinking": row.thinking if row else getattr(self.settings, f"llm_{role}_thinking"),
                "server_thinking": getattr(self.settings, f"llm_{role}_thinking"),
                "thinking_level": row.thinking_level
                if row
                else getattr(self.settings, f"llm_{role}_thinking_level"),
                "server_thinking_level": getattr(self.settings, f"llm_{role}_thinking_level"),
            }
        return {
            "roles": roles,
            "endpoints": [
                {
                    "id": key,
                    "name": value["name"],
                    "thinking_supported": value["provider"] in {"deepseek", "openai"},
                    "thinking_level_supported": value["provider"] in {"deepseek", "openai"},
                }
                for key, value in self.endpoints.items()
            ],
            "personal_available": self.cipher is not None,
        }

    async def write(self, owner: str, role: Role, value: ModelWrite) -> None:
        if self.cipher is None:
            raise auth_error(503, "personal_models_unavailable")
        if (
            value.endpoint_id not in self.endpoints
            or not value.model.strip()
            or any(char in (value.api_key or "") for char in "\r\n")
            or value.thinking
            and self.endpoints[value.endpoint_id]["provider"] not in {"deepseek", "openai"}
            or value.thinking
            and not value.thinking_level.strip()
        ):
            raise auth_error(422, "invalid_model_settings")
        async with in_transaction() as connection:
            row = await PersonalModel.filter(owner_id=owner, role=role).using_db(connection).first()
            if value.api_key is None:
                if row is None or row.endpoint_id != value.endpoint_id:
                    raise auth_error(422, "model_key_required")
                encrypted = row.encrypted_key
            else:
                if not value.api_key.strip():
                    raise auth_error(422, "model_key_required")
                encrypted = self.cipher.encrypt(value.api_key.encode()).decode()
            await PersonalModel.update_or_create(
                owner_id=owner,
                role=role,
                using_db=connection,
                defaults={
                    "endpoint_id": value.endpoint_id,
                    "model": value.model.strip(),
                    "encrypted_key": encrypted,
                    "thinking": value.thinking,
                    "thinking_level": value.thinking_level,
                },
            )

    async def clear(self, owner: str, role: Role) -> None:
        await PersonalModel.filter(owner_id=owner, role=role).delete()

    async def prepare(
        self, owner: str, roles: tuple[Role, ...] = ROLES, *, allow_server: bool = True
    ) -> OperationModels:
        active = self.settings.model_copy(deep=True)
        rows = await PersonalModel.filter(owner_id=owner, role__in=roles)
        uses_server = any(role not in {row.role for row in rows} for role in roles)
        if uses_server and not allow_server:
            raise auth_error(422, "personal_model_required")
        for row in rows:
            endpoint = self.endpoints.get(row.endpoint_id)
            if endpoint is None or self.cipher is None:
                raise auth_error(422, "invalid_model_settings")
            setattr(active, f"llm_{row.role}_provider", endpoint["provider"])
            setattr(active, f"llm_{row.role}_base_url", endpoint["base_url"])
            setattr(active, f"llm_{row.role}_model", row.model)
            setattr(active, f"llm_{row.role}_thinking", row.thinking)
            setattr(active, f"llm_{row.role}_thinking_level", row.thinking_level)
            try:
                key = self.cipher.decrypt(row.encrypted_key.encode()).decode()
            except InvalidToken:
                raise auth_error(422, "invalid_model_settings") from None
            setattr(active, f"llm_{row.role}_api_key", key)
        if any(not getattr(active, f"llm_{role}_api_key").strip() for role in roles):
            raise auth_error(422, "model_key_required")
        return OperationModels(get_llm_provider(active), uses_server)

    @staticmethod
    def day() -> str:
        return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    async def charge(self, owner: str, connection: BaseDBAsyncClient) -> None:
        if not self.settings.production:
            return
        day = self.day()
        for account, limit in [
            (owner, self.settings.server_daily_user_limit),
            ("__all__", self.settings.server_daily_total_limit),
        ]:
            row, _ = await DailyUsage.get_or_create(owner_id=account, day=day, using_db=connection)
            if row.operations >= limit:
                raise auth_error(429, "server_daily_limit")
            row.operations += 1
            await row.save(using_db=connection, update_fields=["operations"])

    async def usage(self, owner: str) -> dict[str, Any]:
        if not self.settings.production:
            return {"enabled": False}
        day = self.day()
        counts = {
            row.owner_id: row.operations
            for row in await DailyUsage.filter(day=day, owner_id__in=[owner, "__all__"])
        }
        return {
            "enabled": True,
            "day": day,
            "timezone": "Asia/Hong_Kong",
            "used": counts.get(owner, 0),
            "limit": self.settings.server_daily_user_limit,
            "remaining": max(0, self.settings.server_daily_user_limit - counts.get(owner, 0)),
            "server_remaining": max(
                0, self.settings.server_daily_total_limit - counts.get("__all__", 0)
            ),
        }
