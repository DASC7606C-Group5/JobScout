"""The signed-in account's model settings, capability tests and daily allowance."""

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from jobscout.schemas.settings import DailyUsage, DisabledUsage, ModelSettingsResponse
from jobscout.services.auth_service import auth_error
from jobscout.services.identity import owner_id
from jobscout.services.llm_service import ModelServiceError
from jobscout.services.model_settings_service import ModelSettingsService, ModelWrite, Role

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def service(request: Request) -> ModelSettingsService:
    return request.app.state.model_settings  # type: ignore[no-any-return]


@router.get("/models", response_model=ModelSettingsResponse)
async def read_models(request: Request) -> dict[str, Any]:
    return await service(request).read(owner_id())


@router.put("/models/{role}", status_code=204)
async def write_models(request: Request, role: Role, payload: ModelWrite) -> Response:
    await service(request).write(owner_id(), role, payload)
    return Response(status_code=204)


@router.delete("/models/{role}", status_code=204)
async def clear_models(request: Request, role: Role) -> Response:
    await service(request).clear(owner_id(), role)
    return Response(status_code=204)


class ConnectionResult(BaseModel):
    ok: bool


@router.post("/models/{role}/test", response_model=ConnectionResult)
async def test_model(request: Request, role: Role) -> dict[str, bool]:
    auth = request.app.state.auth
    limits = [(f"model-test:{owner_id()}", 10)]
    auth.check_rate(limits)
    auth.failed(limits)
    models = await service(request).prepare(owner_id(), (role,), allow_server=False)
    provider = models.provider.semantic if role == "semantic" else models.provider.decision
    async with request.app.state.sessions.lock:
        request.app.state.sessions.check_capacity()
        request.app.state.sessions.testing_users.add(owner_id())
    try:
        result = await provider.structured(
            ConnectionResult, [{"role": "user", "content": 'Return JSON {"ok": true}.'}]
        )
        if not result.ok:
            raise ModelServiceError("model_output")
        if role == "decision":
            turn = await provider.tool_turn(
                [{"role": "user", "content": "Call check_connection."}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "check_connection",
                            "description": "Check connection",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )
            if (
                len(turn.calls) != 1
                or turn.calls[0].name != "check_connection"
                or turn.calls[0].arguments
            ):
                raise ModelServiceError("model_output")
        return {"ok": True}
    except ModelServiceError as error:
        raise auth_error(502, error.code) from None
    finally:
        request.app.state.sessions.testing_users.discard(owner_id())
        await models.provider.aclose()


@router.get("/usage", response_model=DailyUsage | DisabledUsage)
async def read_usage(request: Request) -> dict[str, Any]:
    return await service(request).usage(owner_id())
