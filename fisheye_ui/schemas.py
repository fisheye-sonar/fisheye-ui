from datetime import datetime
from typing import Any, Dict, List, Optional

from fisheye.enums import ExportType, UpstreamDirectionTypes
from pydantic import BaseModel

from fisheye_ui.enums import JobStatus


class JobCreateRequest(BaseModel):
    """Job creation request schema."""

    input_path: str
    output_dir: Optional[str] = None
    upstream_direction: UpstreamDirectionTypes = UpstreamDirectionTypes.LEFT
    distance_offset: float = 0.0
    export_options: List[ExportType] = [
        ExportType.SUMMARY_CSV,
        ExportType.DETAILED_CSV,
        ExportType.FC,
    ]
    platform: Dict[str, Any]
    # Set once the user has confirmed they want to rerun over a location that
    # already has predictions - see routes/jobs.py's create_job.
    confirm_rerun: bool = False


class JobResponse(BaseModel):
    """Job response schema."""

    id: str
    status: JobStatus
    created_at: datetime
    output_dir: Optional[str] = None
    error: Optional[str] = None
    results: Optional[List] = None
    config: Dict[str, Any]


class JobCreatedResponse(BaseModel):
    """Job creation response schema."""

    id: str
    output_dir: str


class OutputFile(BaseModel):
    """Output file schema."""

    filename: str
    size_bytes: int


class OutputListResponse(BaseModel):
    """Output list response schema."""

    files: List[OutputFile]
