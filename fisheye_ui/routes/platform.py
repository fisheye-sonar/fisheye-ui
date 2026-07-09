from fastapi import APIRouter
from fisheye.common.system import detect_platform
from pydantic import BaseModel

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformResponse(BaseModel):
    """Recommended platform response schema."""

    device: str


@router.get("", response_model=PlatformResponse)
async def get_platform():
    """Recommend a device (cuda/mps/cpu) for the current machine."""
    return PlatformResponse(device=detect_platform())
