import asyncio
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/files", tags=["files"])


class PickedPath(BaseModel):
    """Model for the path that is chosen."""

    path: str


async def _run_picker(script: str) -> str | None:
    """Run the AppleScript to pick a file."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        ),
    )
    if result.returncode != 0:
        return None  # user cancelled
    return result.stdout.strip()


def _pick_file_linux() -> str | None:
    """Linux-specific function to pick a file."""
    result = subprocess.run(
        [
            "zenity",
            "--file-selection",
            "--title=Select ARIS or DDF file",
            "--file-filter=*.aris *.ddf",
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _pick_directory_linux() -> str | None:
    """Linux-specific function to pick a directory."""
    result = subprocess.run(
        ["zenity", "--file-selection", "--directory", "--title=Select folder"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


@router.get("/pick-file", response_model=PickedPath)
async def pick_file():
    """Wrapper around _pick_file_linux that returns a PickedPath."""
    path = None
    if sys.platform == "darwin":
        path = await _run_picker(
            'POSIX path of (choose file of type {"aris", "ddf"} with prompt "Select an ARIS or DDF file")'
        )
    elif sys.platform.startswith("linux"):
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _pick_file_linux)
    else:
        raise HTTPException(
            status_code=501, detail="File picker not supported on this platform"
        )

    if not path:
        raise HTTPException(status_code=204, detail="No file selected")

    return PickedPath(path=path)


@router.get("/pick-directory", response_model=PickedPath)
async def pick_directory():
    """Wrapper around _pick_directory_linux that returns a PickedPath."""
    path = None
    if sys.platform == "darwin":
        path = await _run_picker(
            'POSIX path of (choose folder with prompt "Select a folder containing ARIS or DDF files")'
        )
    elif sys.platform.startswith("linux"):
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _pick_directory_linux)
    else:
        raise HTTPException(
            status_code=501, detail="File picker not supported on this platform"
        )

    if not path:
        raise HTTPException(status_code=204, detail="No folder selected")

    return PickedPath(path=path)
