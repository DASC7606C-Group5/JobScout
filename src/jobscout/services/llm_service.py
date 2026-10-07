"""LangChain model integrations with per-operation limits and validated business output."""

import asyncio
import json
import math
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any, Literal, Protocol

import httpx
import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import BaseChatOpenAI
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

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
_RETRY_DELAY_SECONDS = 0.25
type ModelRole = Literal["semantic", "decision"]


def _new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False)


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
    """Use the model's function-call interface; do not store or display its private reasoning."""

    calls: list[ToolCall] = Field(min_length=1, max_length=4)
    _reasoning_content: str | None = PrivateAttr(default=None)

    def assistant_message(self) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            **(
                {"reasoning_content": self._reasoning_content}
                if self._reasoning_content is not None
                else {}
            ),
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in self.calls
            ],
        }


def _validate_tool_arguments(response: object) -> None:
    """Reject arrays before LangChain normalizes falsy tool arguments into empty objects."""
    payload = response.model_dump() if isinstance(response, openai.BaseModel) else response
    if not isinstance(payload, dict):
        return
    for choice in payload.get("choices") or []:
        for call in choice.get("message", {}).get("tool_calls") or []:
            if call["type"] != "function" or not isinstance(
                json.loads(call["function"]["arguments"]), dict
            ):
                raise ModelServiceError("model_output")


class OpenAIChatModel(ChatOpenAI):
    def _create_chat_result(
        self,
        response: dict[str, Any] | openai.BaseModel,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        _validate_tool_arguments(response)
        return super()._create_chat_result(response, generation_info)


class DeepSeekChatModel(ChatDeepSeek):
    """Preserve thinking replies in subsequent tool requests in langchain-deepseek 1.1.1."""

    def _create_chat_result(
        self,
        response: dict[str, Any] | openai.BaseModel,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        _validate_tool_arguments(response)
        return super()._create_chat_result(response, generation_info)

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        for message, outgoing in zip(messages, payload["messages"], strict=True):
            if isinstance(message, AIMessage):
                reasoning = message.additional_kwargs.get("reasoning_content")
                if isinstance(reasoning, str):
                    outgoing["reasoning_content"] = reasoning
        return payload


class LangChainModelProvider:
    """A role-specific model factory with one repair and one transient retry per call.

    LangChain owns requests, message conversion, JSON parsing and tool binding.
    JobScout keeps deadline, retry and output rules consistent across providers.
    """

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
        self._client = client
        self._usage = ModelUsage()
        self._run_usage: ContextVar[ModelUsage | None] = ContextVar("run_model_usage", default=None)
        self.model: str = getattr(settings, f"llm_{role}_model")
        self.provider_name: str = getattr(settings, f"llm_{role}_provider")
        self.thinking: bool = getattr(settings, f"llm_{role}_thinking")
        if self.provider_name not in {"deepseek", "openai", "openai_compatible"} or (
            self.thinking and self.provider_name == "openai_compatible"
        ):
            raise ModelServiceError("model_configuration")

    @property
    def cache_identity(self) -> tuple[str, str, str, bool]:
        return (self.provider_name, self._base_url, self.model, self.thinking)

    async def aclose(self) -> None:
        """Models and owned clients close per call; injected clients belong to their caller."""

    def _validate_configuration(self) -> None:
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
            or (self._client is not None and self._client.follow_redirects)
        ):
            raise ModelServiceError("model_configuration")

    @asynccontextmanager
    async def _chat_model(self) -> AsyncIterator[BaseChatOpenAI]:
        self._validate_configuration()
        if self._client is None:
            async with _new_http_client() as client:
                model = self._create_model(client)
                try:
                    yield model
                finally:
                    model.root_client.close()
        else:
            model = self._create_model(self._client)
            try:
                yield model
            finally:
                model.root_client.close()

    def _create_model(self, client: httpx.AsyncClient) -> BaseChatOpenAI:
        parameters: dict[str, Any] = {
            "model": self.model,
            "api_key": self._api_key,
            "base_url": self._base_url,
            "timeout": self._timeout,
            "max_retries": 0,
            "http_async_client": client,
            "http_socket_options": (),
            "use_responses_api": False,
            "cache": False,
            "verbose": False,
        }
        if self.provider_name == "deepseek":
            parameters.update(
                max_tokens=self._max_tokens,
                extra_body={"thinking": {"type": "enabled" if self.thinking else "disabled"}},
            )
            return DeepSeekChatModel(**parameters)
        if self.provider_name == "openai":
            parameters["max_tokens"] = self._max_tokens
            if self.thinking:
                parameters["reasoning_effort"] = "high"
        else:
            parameters["extra_body"] = {"max_tokens": self._max_tokens}
        return OpenAIChatModel(**parameters)

    @property
    def usage(self) -> ModelUsage:
        """Return detached counters without retaining messages, keys or reasoning."""
        return self._usage.model_copy()

    @contextmanager
    def usage_scope(self, usage: ModelUsage | None = None) -> Iterator[ModelUsage]:
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

    @asynccontextmanager
    async def _operation(self, deadline: float | None) -> AsyncIterator[float]:
        try:
            self._validate_configuration()
            end = asyncio.get_running_loop().time() + self._timeout
            if deadline is not None:
                if not math.isfinite(deadline):
                    raise ModelServiceError("model_input")
                end = min(end, deadline)
            self._remaining(end)
            # Never export applicant data or private tool reasoning to remote tracing.
            with tracing_context(enabled=False):
                async with asyncio.timeout_at(end):
                    yield end
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

    async def _invoke(
        self,
        runnable: Runnable[LanguageModelInput, Any],
        messages: list[dict[str, Any]],
        deadline: float,
        retry_used: list[bool],
    ) -> Any:
        while True:
            self._remaining(deadline)
            self._count("requests")
            try:
                return await runnable.ainvoke(messages, config={"callbacks": []})
            except openai.APIStatusError as error:
                if error.status_code in {401, 403}:
                    raise ModelServiceError("model_auth") from None
                transient = error.status_code in _TRANSIENT_STATUS or 500 <= error.status_code < 600
                if not transient or retry_used[0]:
                    raise ModelServiceError("model_http") from None
            except openai.APIConnectionError as error:
                if retry_used[0]:
                    raise ModelServiceError(
                        "model_timeout"
                        if isinstance(error, openai.APITimeoutError)
                        else "model_transport"
                    ) from None
            except (
                openai.APIError,
                openai.LengthFinishReasonError,
                openai.ContentFilterFinishReasonError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
                AttributeError,
            ):
                raise ModelServiceError("model_output") from None
            retry_used[0] = True
            self._count("retries")
            await asyncio.sleep(min(_RETRY_DELAY_SECONDS, self._remaining(deadline)))

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        async with self._operation(deadline) as end:
            if not messages or not tools:
                raise ModelServiceError("model_input")
            async with self._chat_model() as model:
                try:
                    runnable = model.bind_tools(
                        tools,
                        tool_choice="auto"
                        if self.provider_name == "deepseek" and self.thinking
                        else "required",
                    )
                except ValueError, TypeError:
                    raise ModelServiceError("model_input") from None
                response = await self._invoke(runnable, messages, end, [False])
            try:
                self._record_usage(response)
                if (
                    not isinstance(response, AIMessage)
                    or response.response_metadata.get("finish_reason") != "tool_calls"
                    or response.invalid_tool_calls
                ):
                    raise ValueError
                calls = [
                    ToolCall.model_validate(
                        {"id": call["id"], "name": call["name"], "arguments": call["args"]}
                    )
                    for call in response.tool_calls
                ]
                if len({call.id for call in calls}) != len(calls):
                    raise ValueError
                result = ToolTurn(calls=calls)
                if self.provider_name == "deepseek" and self.thinking:
                    reasoning = response.additional_kwargs.get("reasoning_content")
                    if not isinstance(reasoning, str):
                        raise ValueError
                    result._reasoning_content = reasoning
            except ValueError, TypeError, KeyError:
                raise ModelServiceError("model_output") from None
            self._remaining(end)
            return result

    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT:
        self._count("structured_calls")
        async with self._operation(deadline) as end:
            prompt = self._prepare_messages(schema, messages)
            async with self._chat_model() as model:
                runnable = model.with_structured_output(
                    schema, method="json_mode", include_raw=True
                )
                retry_used = [False]
                for attempt in range(2):
                    content = None
                    try:
                        response = await self._invoke(runnable, prompt, end, retry_used)
                    except ModelServiceError as error:
                        if error.code != "model_output":
                            raise
                    else:
                        raw = response["raw"]
                        self._record_usage(raw)
                        if isinstance(raw, AIMessage):
                            content = raw.content if isinstance(raw.content, str) else None
                            if raw.response_metadata.get("finish_reason") == "stop":
                                try:
                                    if not isinstance(json.loads(content or ""), dict):
                                        raise ValueError
                                    parsed = response["parsed"]
                                    if (
                                        isinstance(parsed, schema)
                                        and response["parsing_error"] is None
                                    ):
                                        self._remaining(end)
                                        return parsed
                                except ValueError:
                                    pass
                    if attempt == 1:
                        raise ModelServiceError("model_output")
                    self._remaining(end)
                    self._count("repairs")
                    if content is not None:
                        prompt.append({"role": "assistant", "content": content})
                    prompt.append({"role": "user", "content": JSON_REPAIR_PROMPT})
        raise ModelServiceError("model_output")

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

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise ModelServiceError("model_timeout")
        return remaining

    def _record_usage(self, message: object) -> None:
        if not isinstance(message, AIMessage):
            return
        usage = message.response_metadata.get("token_usage")
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
    """Route JSON extraction and tool selection to separate models with shared usage counters."""

    def __init__(self, semantic: LangChainModelProvider, decision: LangChainModelProvider) -> None:
        self.semantic = semantic
        self.decision = decision

    @property
    def model(self) -> str:
        return self.semantic.model

    @property
    def models(self) -> dict[str, str]:
        return {"semantic": self.semantic.model, "decision": self.decision.model}

    @property
    def cache_identity(self) -> tuple[str, str, str, bool]:
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
        provider not in {"deepseek", "openai", "openai_compatible"}
        for provider in (
            active_settings.llm_semantic_provider,
            active_settings.llm_decision_provider,
        )
    ):
        raise ModelServiceError("model_configuration")
    return ModelRouter(
        LangChainModelProvider(active_settings, role="semantic"),
        LangChainModelProvider(active_settings, role="decision"),
    )
