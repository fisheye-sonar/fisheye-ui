import asyncio
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import anyio
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import job_manager
from fisheye_ui.paths import JOBS_DIR, UPLOAD_DIR

logger = structlog.get_logger()

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_UPLOAD_SUFFIXES = {".aris", ".ddf"}

# Safety net behind the immediate per-job cleanup in job_manager.py: catches
# uploads that never became a job (abandoned) and output dirs a job finished
# writing to but that are still waiting on _cleanup_upload_input's rmdir
# (i.e. output_dir wasn't overridden, so outputs landed here too) - this
# gives users a day to download results before the directory is reclaimed.
UPLOAD_MAX_AGE_SECONDS = 24 * 60 * 60
UPLOAD_SWEEP_INTERVAL_SECONDS = 60 * 60


def _sweep_stale_uploads() -> None:
    if not UPLOAD_DIR.is_dir():
        return
    in_use = job_manager.active_upload_dirs()
    now = time.time()
    for entry in UPLOAD_DIR.iterdir():
        if not entry.is_dir() or entry in in_use:
            continue
        try:
            age = now - entry.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > UPLOAD_MAX_AGE_SECONDS:
            shutil.rmtree(entry, ignore_errors=True)


def _sweep_stale_job_records() -> None:
    """Counterpart to _sweep_stale_uploads for persisted job records
    (job_manager.py) - same 24h window, same schedule, so there's one
    retention policy rather than two. Skips a record still PENDING/RUNNING
    even if its file is somehow old, mirroring active_upload_dirs' guard."""
    if not JOBS_DIR.is_dir():
        return
    now = time.time()
    for entry in JOBS_DIR.glob("*.json"):
        job_id = entry.stem
        job = job_manager.get_job(job_id)
        if job is not None and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            continue
        try:
            age = now - entry.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > UPLOAD_MAX_AGE_SECONDS:
            entry.unlink(missing_ok=True)
            job_manager.forget(job_id)


def _sweep_loop() -> None:
    while True:
        try:
            _sweep_stale_uploads()
            _sweep_stale_job_records()
        except Exception:
            logger.exception("upload_sweep_failed")
        time.sleep(UPLOAD_SWEEP_INTERVAL_SECONDS)


def start_upload_sweeper() -> None:
    """Start the background thread that periodically deletes stale upload
    directories. Called once from app startup."""
    threading.Thread(target=_sweep_loop, daemon=True).start()


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


@router.post("/file-selection", response_model=PickedPath)
async def create_file_selection():
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


@router.post("/directory-selection", response_model=PickedPath)
async def create_directory_selection():
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


@router.post("/upload", response_model=PickedPath, status_code=201)
async def upload_file(request: Request, filename: str):
    """Stream an uploaded ARIS/DDF file straight to disk and return its path.

    Counterpart to the OS-native pickers above for deployments where the
    server isn't running on the user's own machine (e.g. a remote GPU
    worker), so there's no local filesystem to pick a path from.

    Takes the raw request body so files (up to ~1.5GB) are written to their final path in a single pass -
    multipart's `UploadFile` already buffers the whole upload to a spooled
    temp file before the handler runs, so copying it again afterward would
    write it to disk twice. Each chunk write is offloaded to a thread so
    the event loop (and every other job's progress websocket) isn't
    blocked while a large file is being written.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail="File must be an ARIS or DDF file")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_upload_dir = Path(tempfile.mkdtemp(dir=UPLOAD_DIR))
    dest = job_upload_dir / Path(filename).name

    with dest.open("wb") as out:
        async for chunk in request.stream():
            await anyio.to_thread.run_sync(out.write, chunk)

    return PickedPath(path=str(dest))
