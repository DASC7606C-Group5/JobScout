"""HTTP routes reserved for the Session API."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
