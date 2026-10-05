"""Typed, injectable native async DeepSeek JSON provider."""

import asyncio
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobscout.config import Settings, get_settings
from jobscout.schemas.model import ModelUsage
from jobscout.services.prompts import JSON_REPAIR_PROMPT, STRUCTURED_OUTPUT_PROMPT

_ERROR_MESSAGES = {
    "model_configuration": "The model provider is not configured correctly.",
    "model_input": "The model request is not valid.",
    "model_auth": "The model provider rejected its credentials.",
    "model_timeout": "The model operation exceeded its time limit.",
    "model_transport": "The model provider could not be reached.",
    "model_http": "The model provider could not complete the request.",
    "model_output": "The model provider did not return valid structured output.",
}
_TRANSIENT_STATUS = {408, 425, 429}
type ModelRole = Literal["semantic", "decision"]


class ModelServiceError(RuntimeError):
    """Internal provider error with a fixed code and message, never upstream response text."""

    def __init__(self, code: str = "model_output") -> None:
        self.code = code if code in _ERROR_MESSAGES else "model_output"
        self.message = _ERROR_MESSAGES[self.code]
        super().__init__(self.message)


class LLMProvider(Protocol):
    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT: ...


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class ToolTurn(BaseModel):
    """Native function calls only; model reasoning is never persisted or displayed."""

    calls: list[ToolCall] = Field(min_length=1, max_length=4)

    def assistant_message(self) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in self.calls
            ],
        }


class DeepSeekProvider:
    """One repair and one transient retry per call, sharing an absolute deadline.

    An injected client is borrowed, not closed. Otherwise a client is opened and
    closed for each structured call, so providers need no application shutdown hook.
    """

    provider_name = "deepseek"

    def __init__(
        self,
        settings: Settings,
        *,
        role: ModelRole = "semantic",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if role not in {"semantic", "decision"}:
            raise ModelServiceError("model_configuration")
        self._base_url = getattr(settings, f"llm_{role}_base_url")
        self._api_key = getattr(settings, f"llm_{role}_api_key")
        self._timeout = settings.llm_timeout
        self._max_tokens = settings.llm_max_tokens
        self._retry_delay = settings.llm_retry_delay
        self._client = client
        self._usage = ModelUsage()
        self._run_usage: ContextVar[ModelUsage | None] = ContextVar("run_model_usage", default=None)
        self.model: str = getattr(settings, f"llm_{role}_model")

    @property
    def cache_identity(self) -> tuple[str, str, str]:
        return (self.provider_name, self._base_url, self.model)

    async def aclose(self) -> None:
        """Lifecycle hook; per-call clients self-close and borrowed clients remain owned by caller."""

    def _request_url(self) -> str:
        if not self.model.strip() or not self._api_key.strip():
            raise ModelServiceError("model_configuration")
        try:
            url = httpx.URL(self._base_url.rstrip("/"))
        except httpx.InvalidURL:
            raise ModelServiceError("model_configuration") from None
        if (
            url.scheme != "https"
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or any(character in self._api_key for character in "\r\n")
        ):
            raise ModelServiceError("model_configuration")
        return str(url).rstrip("/") + "/chat/completions"

    @property
    def usage(self) -> ModelUsage:
        """Return a detached counter snapshot; no messages or reasoning are retained."""
        return self._usage.model_copy()

    @contextmanager
    def usage_scope(self, usage: ModelUsage | None = None) -> Iterator[ModelUsage]:
        """Counters inherited by this run's child tasks, isolated from concurrent runs."""
        usage = usage if usage is not None else ModelUsage()
        token = self._run_usage.set(usage)
        try:
            yield usage
        finally:
            self._run_usage.reset(token)

    def _count(self, field: str, amount: int = 1) -> None:
        setattr(self._usage, field, getattr(self._usage, field) + amount)
        scoped = self._run_usage.get()
        if scoped is not None:
            setattr(scoped, field, getattr(scoped, field) + amount)

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        """Request standard DeepSeek function calls with one transient retry."""
        try:
            url = self._request_url()
            end = asyncio.get_running_loop().time() + self._timeout
            if deadline is not None:
                if not math.isfinite(deadline):
                    raise ModelServiceError("model_input")
                end = min(end, deadline)
            if not messages or not tools:
                raise ModelServiceError("model_input")
            async with asyncio.timeout_at(end):
                if self._client is not None:
                    result = await self._tool_turn(self._client, url, messages, tools, end)
                else:
                    async with httpx.AsyncClient() as client:
                        result = await self._tool_turn(client, url, messages, tools, end)
        except asyncio.CancelledError:
            self._count("cancellations")
            raise
        except TimeoutError:
            self._count("failed_calls")
            raise ModelServiceError("model_timeout") from None
        except ModelServiceError:
            self._count("failed_calls")
            raise
        self._count("successful_calls")
        return result

    async def _tool_turn(
        self,
        client: httpx.AsyncClient,
        url: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        deadline: float,
    ) -> ToolTurn:
        retried = False
        while True:
            self._count("requests")
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": "required",
                        "thinking": {"type": "disabled"},
                        "max_tokens": self._max_tokens,
                        "stream": False,
                    },
                    timeout=httpx.Timeout(self._remaining(deadline)),
                    follow_redirects=False,
                )
            except httpx.TransportError as error:
                if retried:
                    raise ModelServiceError(
                        "model_timeout"
                        if isinstance(error, httpx.TimeoutException)
                        else "model_transport"
                    ) from None
                retried = True
                await self._retry(deadline)
                continue
            except httpx.InvalidURL, httpx.RequestError:
                raise ModelServiceError("model_transport") from None
            if response.status_code in {401, 403}:
                raise ModelServiceError("model_auth")
            if response.status_code in _TRANSIENT_STATUS or 500 <= response.status_code < 600:
                if retried:
                    raise ModelServiceError("model_http")
                retried = True
                await self._retry(deadline)
                continue
            if not response.is_success:
                raise ModelServiceError("model_http")
            try:
                payload = response.json()
                self._record_usage(payload)
                choice = payload["choices"][0]
                if choice["finish_reason"] != "tool_calls":
                    raise ValueError
                if any(call["type"] != "function" for call in choice["message"]["tool_calls"]):
                    raise ValueError
                calls = [
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=json.loads(call["function"]["arguments"]),
                    )
                    for call in choice["message"]["tool_calls"]
                    if call["type"] == "function"
                ]
                if len({call.id for call in calls}) != len(calls):
                    raise ValueError
                result = ToolTurn(calls=calls)
            except ValueError, KeyError, TypeError, IndexError:
                raise ModelServiceError("model_output") from None
            self._remaining(deadline)
            return result

    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT:
        self._count("structured_calls", 1)
        try:
            url = self._request_url()
            end = asyncio.get_running_loop().time() + self._timeout
            if deadline is not None:
                if not math.isfinite(deadline):
                    raise ModelServiceError("model_input")
                end = min(end, deadline)
            self._remaining(end)
            prompt = self._prepare_messages(schema, messages)
            async with asyncio.timeout_at(end):
                if self._client is not None:
                    result = await self._structured(self._client, url, schema, prompt, end)
                else:
                    async with httpx.AsyncClient() as client:
                        result = await self._structured(client, url, schema, prompt, end)
        except asyncio.CancelledError:
            self._count("cancellations", 1)
            raise
        except TimeoutError:
            self._count("failed_calls", 1)
            raise ModelServiceError("model_timeout") from None
        except ModelServiceError:
            self._count("failed_calls", 1)
            raise
        self._count("successful_calls", 1)
        return result

    @staticmethod
    def _prepare_messages(
        schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        if not messages or any(
            set(message) != {"role", "content"}
            or message["role"] not in {"system", "user", "assistant"}
            or not isinstance(message["content"], str)
            for message in messages
        ):
            raise ModelServiceError("model_input")
        instruction = STRUCTURED_OUTPUT_PROMPT + json.dumps(
            schema.model_json_schema(), ensure_ascii=False
        )
        return [{"role": "system", "content": instruction}, *[dict(item) for item in messages]]

    async def _structured[SchemaT: BaseModel](
        self,
        client: httpx.AsyncClient,
        url: str,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        deadline: float,
    ) -> SchemaT:
        retried = False
        repaired = False
        while True:
            remaining = self._remaining(deadline)
            self._count("requests", 1)
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "disabled"},
                        "max_tokens": self._max_tokens,
                        "stream": False,
                    },
                    timeout=httpx.Timeout(remaining),
                    follow_redirects=False,
                )
            except httpx.TransportError as error:
                if retried:
                    code = (
                        "model_timeout"
                        if isinstance(error, httpx.TimeoutException)
                        else "model_transport"
                    )
                    raise ModelServiceError(code) from None
                retried = True
                await self._retry(deadline)
                continue
            except httpx.InvalidURL, httpx.RequestError:
                raise ModelServiceError("model_transport") from None

            if response.status_code in {401, 403}:
                raise ModelServiceError("model_auth")
            if response.status_code in _TRANSIENT_STATUS or 500 <= response.status_code < 600:
                if retried:
                    raise ModelServiceError("model_http")
                retried = True
                await self._retry(deadline)
                continue
            if not response.is_success:
                raise ModelServiceError("model_http")

            content = self._content(response)
            if content is not None:
                try:
                    # JSON mode promises an object, not a scalar or a fenced block.
                    if not isinstance(json.loads(content), dict):
                        raise ValueError
                    result = schema.model_validate_json(content)
                except ValueError, ValidationError:
                    pass
                else:
                    self._remaining(deadline)
                    return result
            if repaired:
                raise ModelServiceError("model_output")
            self._remaining(deadline)
            repaired = True
            self._count("repairs", 1)
            if content is not None:
                messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": JSON_REPAIR_PROMPT,
                }
            )

    async def _retry(self, deadline: float) -> None:
        remaining = self._remaining(deadline)
        self._count("retries", 1)
        await asyncio.sleep(min(self._retry_delay, remaining))

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise ModelServiceError("model_timeout")
        return remaining

    def _content(self, response: httpx.Response) -> str | None:
        try:
            data = response.json()
        except ValueError, UnicodeError:
            return None
        if not isinstance(data, dict):
            return None
        self._record_usage(data)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return None
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            return None
        message = choice.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        return content if isinstance(content, str) else None

    def _record_usage(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        usage = data.get("usage")
        if isinstance(usage, dict):
            prompt = self._token_count(usage.get("prompt_tokens"))
            completion = self._token_count(usage.get("completion_tokens"))
            total = self._token_count(usage.get("total_tokens"), prompt + completion)
            self._count("prompt_tokens", prompt)
            self._count("completion_tokens", completion)
            self._count("total_tokens", total)

    @staticmethod
    def _token_count(value: object, default: int = 0) -> int:
        return value if type(value) is int and value >= 0 else default


class ModelRouter:
    """Semantic structured calls and decision tool calls share only their run counters."""

    def __init__(self, semantic: DeepSeekProvider, decision: DeepSeekProvider) -> None:
        self.semantic = semantic
        self.decision = decision

    @property
    def model(self) -> str:
        return self.semantic.model

    @property
    def models(self) -> dict[str, str]:
        return {"semantic": self.semantic.model, "decision": self.decision.model}

    @property
    def cache_identity(self) -> tuple[str, str, str]:
        return self.semantic.cache_identity

    @property
    def usage(self) -> ModelUsage:
        semantic = self.semantic.usage
        decision = self.decision.usage
        return ModelUsage.model_validate(
            {
                field: getattr(semantic, field) + getattr(decision, field)
                for field in ModelUsage.model_fields
            }
        )

    @contextmanager
    def usage_scope(self) -> Iterator[ModelUsage]:
        usage = ModelUsage()
        with self.semantic.usage_scope(usage), self.decision.usage_scope(usage):
            yield usage

    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT:
        return await self.semantic.structured(schema, messages, deadline=deadline)

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        return await self.decision.tool_turn(messages, tools, deadline=deadline)

    async def aclose(self) -> None:
        await self.semantic.aclose()
        await self.decision.aclose()


def get_llm_provider(settings: Settings | None = None) -> ModelRouter:
    active_settings = settings or get_settings()
    if any(
        provider != "deepseek"
        for provider in (
            active_settings.llm_semantic_provider,
            active_settings.llm_decision_provider,
        )
    ):
        raise ModelServiceError("model_configuration")
    return ModelRouter(
        DeepSeekProvider(active_settings, role="semantic"),
        DeepSeekProvider(active_settings, role="decision"),
    )
