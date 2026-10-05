"""Offline provider contract tests using only synthetic inputs and HTTP responses."""

import asyncio
import json
from collections.abc import Callable
from typing import assert_type

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobscout.config import Settings
from jobscout.services.llm_service import (
    DeepSeekProvider,
    LLMProvider,
    ModelServiceError,
    get_llm_provider,
)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    count: int = Field(ge=0)


class AlternateAnswer(BaseModel):
    enabled: bool


@pytest.fixture
def settings() -> Settings:
    return Settings.model_construct(
        llm_provider="deepseek",
        llm_api_key="synthetic-test-token",
        llm_base_url="https://model.example.invalid/v1",
        llm_model="deepseek-flash",
        llm_timeout=2,
        llm_max_tokens=100,
        llm_retry_delay=0,
    )


def reply(
    content: str = '{"name":"synthetic","count":2}',
    *,
    finish_reason: str = "stop",
    usage: dict[str, object] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Synthetic example: 示例资料"}]


def test_json_wire_format_typed_response_and_borrowed_client(settings: Settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return reply()

    async def scenario() -> None:
        original = messages()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            result = await provider.structured(Answer, original)
            assert_type(result, Answer)
            assert result == Answer(name="synthetic", count=2)
            assert not client.is_closed
            assert provider.usage.requests == 1
            assert provider.usage.successful_calls == 1
            assert provider.usage.prompt_tokens == 10
            assert provider.usage.completion_tokens == 5
            assert provider.usage.total_tokens == 15
            snapshot = provider.usage
            snapshot.requests = 999
            assert provider.usage.requests == 1
        assert original == messages()

    asyncio.run(scenario())
    request = requests[0]
    body = json.loads(request.content)
    assert request.url == "https://model.example.invalid/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer synthetic-test-token"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["stream"] is False
    assert body["model"] == "deepseek-flash"
    assert body["max_tokens"] == 100
    assert "JSON" in body["messages"][0]["content"]
    assert body["messages"][1] == messages()[0]
    assert all(0 < value <= 2 for value in request.extensions["timeout"].values())


def test_protocol_accepts_generic_fake_without_configuration() -> None:
    class FakeProvider:
        async def structured[SchemaT: BaseModel](
            self,
            schema: type[SchemaT],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> SchemaT:
            assert messages
            assert deadline == 123.0
            return schema.model_validate_json('{"enabled":true}')

    async def scenario() -> None:
        fake: LLMProvider = FakeProvider()
        result = await fake.structured(AlternateAnswer, messages(), deadline=123.0)
        assert_type(result, AlternateAnswer)
        assert result.enabled

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "```json\n{}\n```",
        "[]",
        '{"name":"synthetic"}',
        '{"name":"synthetic","count":-1}',
        '{"name":"synthetic","count":2,"invented":"extra"}',
    ],
)
def test_one_schema_or_json_repair(settings: Settings, content: str) -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return reply(content) if len(calls) == 1 else reply()

    async def scenario() -> None:
        original = messages()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            assert (await provider.structured(Answer, original)).count == 2
            assert provider.usage.repairs == 1
            assert provider.usage.requests == 2
            assert provider.usage.total_tokens == 30
            assert provider.usage.retries == 0
        assert original == messages()

    asyncio.run(scenario())
    repaired_messages = calls[1]["messages"]
    assert isinstance(repaired_messages, list)
    assert repaired_messages[-2] == {"role": "assistant", "content": content}


@pytest.mark.parametrize(
    "response_factory",
    [
        lambda: httpx.Response(200, content="broken outer JSON"),
        lambda: httpx.Response(200, json={"choices": []}),
        lambda: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        lambda: httpx.Response(200, json=[]),
        lambda: reply(finish_reason="length"),
        lambda: reply(finish_reason="content_filter"),
        lambda: reply("invalid synthetic output"),
    ],
    ids=["envelope", "empty_choices", "null", "array", "truncated", "filtered", "bad_content"],
)
def test_invalid_responses_exhaust_exactly_one_repair_safely(
    settings: Settings, response_factory: Callable[[], httpx.Response]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response_factory()

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages())
            assert caught.value.code == "model_output"
            assert caught.value.__cause__ is None
            assert "synthetic" not in str(caught.value)
            assert provider.usage.requests == 2
            assert provider.usage.repairs == 1
            assert provider.usage.failed_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_one_transient_http_retry(settings: Settings, status: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status, text="synthetic private upstream error")
        return reply()

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            assert (await provider.structured(Answer, messages())).count == 2
            assert provider.usage.retries == 1
            assert provider.usage.repairs == 0

    asyncio.run(scenario())
    assert attempts == 2


@pytest.mark.parametrize(
    "status,code,attempts",
    [
        (401, "model_auth", 1),
        (403, "model_auth", 1),
        (400, "model_http", 1),
        (404, "model_http", 1),
        (429, "model_http", 2),
        (503, "model_http", 2),
    ],
)
def test_http_failure_codes_are_safe_and_bounded(
    settings: Settings, status: int, code: str, attempts: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="synthetic-test-token private synthetic resume")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages())
            assert caught.value.code == code
            assert caught.value.message == str(caught.value)
            assert "synthetic" not in str(caught.value)
            assert "synthetic" not in repr(caught.value)
            assert provider.usage.requests == attempts
            assert provider.usage.failed_calls == 1
            assert provider.usage.repairs == 0

    asyncio.run(scenario())


def test_retry_budget_is_shared_across_repair(settings: Settings) -> None:
    sequence = [httpx.Response(503), reply("broken JSON"), httpx.Response(429), reply()]

    def handler(request: httpx.Request) -> httpx.Response:
        return sequence.pop(0)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError, match="could not complete"):
                await provider.structured(Answer, messages())
            assert provider.usage.retries == 1
            assert provider.usage.repairs == 1
            assert provider.usage.requests == 3

    asyncio.run(scenario())
    assert len(sequence) == 1


def test_repair_can_use_remaining_retry_and_usage_accumulates(settings: Settings) -> None:
    sequence = [reply("broken JSON"), httpx.Response(503), reply()]

    def handler(request: httpx.Request) -> httpx.Response:
        return sequence.pop(0) if sequence else reply()

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            await provider.structured(Answer, messages())
            await provider.structured(Answer, messages())
            assert provider.usage.structured_calls == 2
            assert provider.usage.successful_calls == 2
            assert provider.usage.retries == 1
            assert provider.usage.repairs == 1
            assert provider.usage.requests == 4
            assert provider.usage.total_tokens == 45

    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failure_retries_once(
    settings: Settings, error_type: type[httpx.TransportError]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("synthetic secret upstream error", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages())
            expected = "model_timeout" if error_type is httpx.ReadTimeout else "model_transport"
            assert caught.value.code == expected
            assert caught.value.__cause__ is None
            assert "synthetic" not in str(caught.value)
            assert provider.usage.requests == 2
            assert provider.usage.retries == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("use_deadline", [False, True])
def test_whole_operation_timeout_cancels_pending_http(
    settings: Settings, use_deadline: bool
) -> None:
    finished: list[bool] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
            return reply()
        finally:
            finished.append(True)

    async def scenario() -> None:
        settings.llm_timeout = 2 if use_deadline else 0.02
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            end = asyncio.get_running_loop().time() + 0.02 if use_deadline else None
            with pytest.raises(ModelServiceError) as caught:
                await asyncio.wait_for(provider.structured(Answer, messages(), deadline=end), 1)
            assert caught.value.code == "model_timeout"
            assert provider.usage.requests == 1
            assert provider.usage.failed_calls == 1
            assert provider.usage.cancellations == 0

    asyncio.run(scenario())
    assert finished == [True]


def test_retry_sleep_does_not_reset_timeout(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "100000"})

    async def scenario() -> None:
        settings.llm_timeout = 0.02
        settings.llm_retry_delay = 1
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await asyncio.wait_for(provider.structured(Answer, messages()), 1)
            assert caught.value.code == "model_timeout"
            assert provider.usage.requests == 1

    asyncio.run(scenario())


def test_expired_deadline_makes_no_http_request(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Expired operations must not send documents")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages(), deadline=0)
            assert caught.value.code == "model_timeout"
            assert provider.usage.requests == 0

    asyncio.run(scenario())


def test_external_cancellation_propagates_without_retry(settings: Settings) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            started.set()
            try:
                await asyncio.sleep(10)
                return reply()
            finally:
                stopped.set()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            task = asyncio.create_task(provider.structured(Answer, messages()))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stopped.is_set()
            assert provider.usage.cancellations == 1
            assert provider.usage.failed_calls == 0
            assert provider.usage.retries == 0
            assert provider.usage.repairs == 0

    asyncio.run(scenario())


def test_concurrent_requests_keep_independent_retry_budgets(settings: Settings) -> None:
    attempts: dict[str, int] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["messages"][1]["content"]
        attempts[text] = attempts.get(text, 0) + 1
        await asyncio.sleep(0)
        return httpx.Response(503) if attempts[text] == 1 else reply()

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            results = await asyncio.gather(
                provider.structured(Answer, [{"role": "user", "content": "synthetic A"}]),
                provider.structured(Answer, [{"role": "user", "content": "synthetic B"}]),
            )
            assert len(results) == 2
            assert provider.usage.requests == 4
            assert provider.usage.retries == 2
            assert provider.usage.successful_calls == 2
            assert provider.usage.total_tokens == 30

    asyncio.run(scenario())


def test_factory_and_configurable_model(settings: Settings) -> None:
    settings.llm_model = "synthetic-alternate-model"
    provider = get_llm_provider(settings)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "synthetic-alternate-model"
    assert "synthetic-test-token" not in repr(settings)
    assert "synthetic-test-token" not in repr(provider)


@pytest.mark.parametrize("provider_name", ["demo", "openai_compatible", "synthetic unknown"])
def test_factory_rejects_unknown_provider_without_fallback(
    settings: Settings, provider_name: str
) -> None:
    settings.llm_provider = provider_name
    with pytest.raises(ModelServiceError) as caught:
        get_llm_provider(settings)
    assert caught.value.code == "model_configuration"
    assert provider_name not in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("llm_api_key", ""),
        ("llm_api_key", "   "),
        ("llm_api_key", "synthetic\r\nsecret"),
        ("llm_model", ""),
        ("llm_base_url", ""),
        ("llm_base_url", "http://model.example.invalid"),
        ("llm_base_url", "https://user:secret@model.example.invalid"),
        ("llm_base_url", "https://model.example.invalid?token=secret"),
        ("llm_base_url", "https://model.example.invalid#secret"),
    ],
)
def test_missing_or_unsafe_configuration_fails_before_io(
    settings: Settings, field: str, value: str
) -> None:
    setattr(settings, field, value)

    async def scenario() -> None:
        provider = DeepSeekProvider(settings)
        with pytest.raises(ModelServiceError) as caught:
            await provider.structured(Answer, messages())
        assert caught.value.code == "model_configuration"
        assert "secret" not in str(caught.value)
        assert provider.usage.requests == 0
        assert provider.usage.failed_calls == 1

    asyncio.run(scenario())


def test_factory_missing_key_is_lazy_and_close_is_idempotent(settings: Settings) -> None:
    settings.llm_api_key = ""
    provider = get_llm_provider(settings)
    assert isinstance(provider, DeepSeekProvider)

    async def scenario() -> None:
        await provider.aclose()
        await provider.aclose()
        with pytest.raises(ModelServiceError) as caught:
            await provider.structured(Answer, messages())
        assert caught.value.code == "model_configuration"
        assert provider.usage.requests == 0

    asyncio.run(scenario())


def test_aclose_does_not_close_borrowed_client(settings: Settings) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: reply())
        ) as client:
            provider = DeepSeekProvider(settings, client=client)
            await provider.aclose()
            await provider.aclose()
            assert not client.is_closed
            assert (await provider.structured(Answer, messages())).count == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [0, -1, 181, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(settings: Settings, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({**settings.model_dump(), "llm_timeout": value})


def test_redirects_do_not_forward_credentials(settings: Settings) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(307, headers={"Location": "https://other.example.invalid"})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages())
            assert caught.value.code == "model_http"

    asyncio.run(scenario())
    assert attempts == 1


def test_invalid_usage_is_not_trusted(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return reply(usage={"prompt_tokens": -7, "completion_tokens": True, "total_tokens": "99"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            await provider.structured(Answer, messages())
            assert provider.usage.total_tokens == 0
            assert provider.usage.prompt_tokens == 0
            assert provider.usage.completion_tokens == 0

    asyncio.run(scenario())


def test_provider_closes_owned_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: reply()))
    monkeypatch.setattr("jobscout.services.llm_service.httpx.AsyncClient", lambda: client)

    async def scenario() -> None:
        await DeepSeekProvider(settings).structured(Answer, messages())
        assert client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_deadline_is_rejected(settings: Settings, deadline: float) -> None:
    async def scenario() -> None:
        provider = DeepSeekProvider(settings)
        with pytest.raises(ModelServiceError) as caught:
            await provider.structured(Answer, messages(), deadline=deadline)
        assert caught.value.code == "model_input"
        assert provider.usage.requests == 0

    asyncio.run(scenario())


def test_transport_retry_can_recover(settings: Settings) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("synthetic transient", request=request)
        return reply()

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            assert (await provider.structured(Answer, messages())).count == 2
            assert provider.usage.requests == 2
            assert provider.usage.retries == 1
            assert provider.usage.failed_calls == 0

    asyncio.run(scenario())


def test_usage_total_falls_back_to_reported_components(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return reply(usage={"prompt_tokens": 2, "completion_tokens": 3})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            await provider.structured(Answer, messages())
            assert provider.usage.total_tokens == 5

    asyncio.run(scenario())


def test_valid_json_returned_after_deadline_is_not_accepted(settings: Settings) -> None:
    class LateClient(httpx.AsyncClient):
        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                return reply()
            return reply()

    async def scenario() -> None:
        settings.llm_timeout = 0.02
        async with LateClient() as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as caught:
                await provider.structured(Answer, messages())
            assert caught.value.code == "model_timeout"
            assert provider.usage.successful_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [[], [{"role": "tool", "content": "synthetic"}]])
def test_invalid_messages_fail_before_io(settings: Settings, invalid: list[dict[str, str]]) -> None:
    async def scenario() -> None:
        provider = DeepSeekProvider(settings)
        with pytest.raises(ModelServiceError) as caught:
            await provider.structured(Answer, invalid)
        assert caught.value.code == "model_input"
        assert provider.usage.requests == 0

    asyncio.run(scenario())


def test_native_tool_call_protocol_preserves_call_identity_and_arguments(
    settings: Settings,
) -> None:
    from jobscout.services.tool_registry import ToolRegistry

    async def scenario() -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "native-call",
                                        "type": "function",
                                        "function": {
                                            "name": "search_jobs",
                                            "arguments": json.dumps(
                                                {
                                                    "direction": "数据分析",
                                                    "source": "jobsdb",
                                                    "keywords": ["Data Analyst"],
                                                }
                                            ),
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with provider.usage_scope() as usage:
                result = await provider.tool_turn(
                    [{"role": "user", "content": "Synthetic search"}], ToolRegistry().schemas()
                )
            assert result.calls[0].id == "native-call"
            assert result.calls[0].arguments["direction"] == "数据分析"
            assert result.assistant_message()["tool_calls"][0]["id"] == "native-call"
            assert usage.requests == 1 and usage.total_tokens == 18
        assert requests[0]["tool_choice"] == "required"
        assert "response_format" not in requests[0]
        assert "tools" in requests[0]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments,finish",
    [("not json", "tool_calls"), ("[]", "tool_calls"), ("{}", "length"), ("{}", "stop")],
)
def test_invalid_native_tool_results_fail_without_exposing_provider_body(
    settings: Settings, arguments: str, finish: str
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": finish,
                            "message": {
                                "content": "PRIVATE_SENTINEL",
                                "tool_calls": [
                                    {
                                        "id": "one",
                                        "type": "function",
                                        "function": {"name": "search_jobs", "arguments": arguments},
                                    }
                                ],
                            },
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)
            with pytest.raises(ModelServiceError) as rejected:
                await provider.tool_turn(
                    [{"role": "user", "content": "Synthetic"}], [{"type": "function"}]
                )
            assert rejected.value.code == "model_output"
            assert "PRIVATE_SENTINEL" not in str(rejected.value)
            assert provider.usage.requests == 1

    asyncio.run(scenario())


def test_usage_scopes_isolate_concurrent_runs_and_inherit_into_child_tasks(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0)
            return reply(usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(settings, client=client)

            async def execute(count: int) -> tuple[int, int]:
                with provider.usage_scope() as usage:
                    await asyncio.gather(
                        *(provider.structured(Answer, messages()) for _ in range(count))
                    )
                return usage.requests, usage.total_tokens

            first, second = await asyncio.gather(execute(1), execute(3))
            assert first == (1, 5)
            assert second == (3, 15)
            assert provider.usage.requests == 4

    asyncio.run(scenario())
