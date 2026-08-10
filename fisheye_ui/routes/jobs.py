import asyncio
import io
import json
import queue
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from fisheye_ui import usage
from fisheye_ui.enums import JobStatus
from fisheye_ui.output_paths import (
    has_existing_predictions,
    next_available_output_dir,
)
from fisheye_ui.job_manager import job_manager
from fisheye_ui.schemas import (
    JobCreateRequest,
    JobCreatedResponse,
    JobResponse,
    OutputFile,
    OutputListResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Set by Caddy's basic_auth on the cloud deployment (forwarded as the
# authenticated username - see deploy/gateway/README.md) so per-account job
# limits can be enforced. Absent for desktop/local use, where nothing sits
# in front of this app to authenticate a username - see usage.is_limited.
USER_HEADER = "X-Fisheye-User"


@router.post("", response_model=JobCreatedResponse, status_code=201)
async def create_job(request: JobCreateRequest, http_request: Request):
    username = http_request.headers.get(USER_HEADER, "")
    if usage.is_limited(username) and usage.jobs_used(username) >= usage.MAX_JOBS_PER_USER:
        raise HTTPException(
            status_code=403,
            detail=f"This account has reached its limit of {usage.MAX_JOBS_PER_USER} jobs.",
        )

    input_path = Path(request.input_path)
    # Mirrors job_manager._run's own output_dir fallback so this check looks
    # in the same place the pipeline will actually read/write.
    output_dir = Path(
        request.output_dir or (input_path if input_path.is_dir() else input_path.parent)
    )

    if has_existing_predictions(input_path, output_dir):
        suggested_output_dir = next_available_output_dir(output_dir)
        if not request.confirm_rerun:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Some files at this location already have predictions.",
                    "existing_output_dir": str(output_dir),
                    "suggested_output_dir": str(suggested_output_dir),
                },
            )
        # Write the rerun to a new directory instead of overwriting existing results or having FishEye
        # silently skip every file because the output already exists
        output_dir = suggested_output_dir

    config = request.model_dump(exclude={"confirm_rerun"})
    config["output_dir"] = str(output_dir)
    job_id = job_manager.create_job(config)
    if usage.is_limited(username):
        usage.record_job(username)
    return JobCreatedResponse(id=job_id, output_dir=str(output_dir))


@router.get("/active")
async def get_active(exclude_job_id: Optional[str] = None):
    """Whether any job (other than exclude_job_id, if given) is currently
    pending or running, and how long it's been since the most recent job
    finished.

    Registered before /{job_id} so "active" isn't swallowed as a job_id.
    With no exclude_job_id, this is the remote-deployment idle-watcher's
    activity signal: it never stops the GPU worker while a job is active,
    and otherwise measures idle time from job start/finish events rather
    than raw HTTP traffic (browsing/composing the form isn't "activity" for
    auto-sleep purposes). The frontend also polls this - excluding the job
    it's currently viewing - to warn the user the shared GPU is busy with
    someone else's job. `idle_seconds` is null if no job has ever finished
    on this worker.
    """
    return {
        "active": job_manager.has_active_jobs(exclude_job_id),
        "idle_seconds": job_manager.idle_seconds(),
    }


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        output_dir=job.output_dir,
        error=job.error,
        results=job.results,
        config=job.config,
    )


@router.delete("/{job_id}", status_code=204)
async def cancel_job(job_id: str):
    cancelled = job_manager.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Job not found or not cancellable")


@router.get("/{job_id}/outputs", response_model=OutputListResponse)
async def list_outputs(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_dir:
        return OutputListResponse(files=[])

    output_dir = Path(job.output_dir)
    if not output_dir.is_dir():
        return OutputListResponse(files=[])

    # Outputs are written next to each source file, which in batch mode can
    # be nested under output_dir
    files = [
        OutputFile(
            filename=f.relative_to(output_dir).as_posix(),
            size_bytes=f.stat().st_size,
        )
        for f in sorted(output_dir.rglob("*"))
        if f.is_file()
    ]
    return OutputListResponse(files=files)


@router.get("/{job_id}/outputs/download-all")
def download_all_outputs(job_id: str):
    # Sync def, not async: zipping thousands of files is blocking CPU/IO work,
    # and FastAPI runs sync handlers in a threadpool so it doesn't stall the
    # event loop (and every other job's progress websocket) while it runs.
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_dir:
        raise HTTPException(status_code=404, detail="No output directory for this job")

    output_dir = Path(job.output_dir)
    if not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="No output directory for this job")

    # Leave .arris/.ddf files out of the zip.
    excluded_suffixes = {".aris", ".ddf"}

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(output_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() not in excluded_suffixes:
                zf.write(f, arcname=f.relative_to(output_dir).as_posix())
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-outputs.zip"'},
    )


@router.websocket("/{job_id}/stream")
async def stream_job_progress(websocket: WebSocket, job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()

    try:
        while True:
            try:
                event = await loop.run_in_executor(
                    None, lambda: job.progress_queue.get(timeout=0.5)
                )
                await websocket.send_text(json.dumps(event, default=str))
            except queue.Empty:
                if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                    break

        await websocket.send_text(
            json.dumps(
                {"event": "done", "status": job.status.value, "error": job.error}
            )
        )
    except WebSocketDisconnect:
        pass


@router.get("/{job_id}/outputs/{file_path:path}")
async def download_output(job_id: str, file_path: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_dir:
        raise HTTPException(status_code=404, detail="No output directory for this job")

    output_dir = Path(job.output_dir).resolve()
    resolved_path = (output_dir / file_path).resolve()

    if not resolved_path.is_relative_to(output_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=resolved_path, filename=resolved_path.name)
