from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

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

    files = [
        OutputFile(filename=f.name, size_bytes=f.stat().st_size)
        for f in sorted(output_dir.iterdir())
        if f.is_file()
    ]
    return OutputListResponse(files=files)


@router.get("/{job_id}/outputs/{filename}")
async def download_output(job_id: str, filename: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_dir:
        raise HTTPException(status_code=404, detail="No output directory for this job")

    output_dir = Path(job.output_dir).resolve()
    file_path = (output_dir / filename).resolve()

    if not str(file_path).startswith(str(output_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=file_path, filename=filename)
