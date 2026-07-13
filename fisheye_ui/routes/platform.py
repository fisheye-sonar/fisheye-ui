import os
import shutil
import sys

from fastapi import APIRouter
from fisheye.common.system import detect_platform
from pydantic import BaseModel

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformResponse(BaseModel):
    """Recommended platform response schema."""

    device: str
    native_file_picker: bool


def _native_file_picker_available() -> bool:
    """Whether an OS file picker can actually be opened on this machine.

    True on macOS. On Linux, only if zenity is installed and a display is
    attached - a headless remote worker has neither. False otherwise
    (e.g. Windows, where the picker routes already return 501).
    """
    if sys.platform == "darwin":
        return True
    if sys.platform.startswith("linux"):
        has_display = bool(
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        )
        return bool(shutil.which("zenity")) and has_display
    return False


@router.get("", response_model=PlatformResponse)
async def get_platform():
    """Recommend a device (cuda/mps/cpu) for the current machine."""
    return PlatformResponse(
        device=detect_platform(),
        native_file_picker=_native_file_picker_available(),
    )
