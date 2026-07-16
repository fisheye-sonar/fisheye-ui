import os
import shutil
import sys
from typing import List, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformResponse(BaseModel):
    """Recommended platform response schema."""

    device: str
    native_file_picker: bool
    available_devices: List[str]


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


def _device_availability() -> Tuple[str, List[str]]:
    """Which inference devices torch reports as usable on this machine, and
    which of those to recommend.

    CPU always works. CUDA/MPS are only included if their respective torch
    backend is actually available (e.g. a headless AWS GPU worker has cuda
    but not mps, and a Mac without an NVIDIA GPU has mps/cpu but not cuda.)
    The full list lets the frontend disable options a job would otherwise
    fail on partway through, instead of the user finding out only after
    submitting; the recommendation prefers cuda, then mps, then cpu.
    """
    devices = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            devices.append("cuda")
        if torch.backends.mps.is_available():
            devices.append("mps")

    except ImportError:
        pass

    recommended = "cuda" if "cuda" in devices else "mps" if "mps" in devices else "cpu"
    return recommended, devices


@router.get("", response_model=PlatformResponse)
async def get_platform():
    """Recommend a device (cuda/mps/cpu) for the current machine."""
    recommended, available = _device_availability()
    return PlatformResponse(
        device=recommended,
        native_file_picker=_native_file_picker_available(),
        available_devices=available,
    )
