import asyncio
import io
import json
import queue
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import job_manager
from fisheye_ui.schemas import (
    JobCreateRequest,
    JobCreatedResponse,
    JobResponse,
    OutputFile,
    OutputListResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobCreatedResponse, status_code=201)
async def create_job(request: JobCreateRequest):
    job_id = job_manager.create_job(request.model_dump())
    return JobCreatedResponse(id=job_id)


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
async def download_all_outputs(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_dir:
        raise HTTPException(status_code=404, detail="No output directory for this job")

    output_dir = Path(job.output_dir)
    if not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="No output directory for this job")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(output_dir.rglob("*")):
            if f.is_file():
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
