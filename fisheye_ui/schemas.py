from datetime import datetime
from typing import Any, Dict, List, Optional

from fisheye.enums import ExportType, UpstreamDirectionTypes
from pydantic import BaseModel, EmailStr, model_validator

from fisheye_ui.enums import JobStatus, TelemetryChoice


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


class FileCount(BaseModel):
    """Per-file counts for telemetry, keyed by position in the batch
    rather than filename. See job_manager.build_telemetry_payload."""

    file_index: int
    absolute_up: int
    absolute_down: int
    net_count: int


class FileTrackStats(BaseModel):
    """Per-file track/count stats for telemetry, sourced from the
    pipeline's processed_file_stats log event."""

    file_index: int
    num_tracks: int
    num_counts: int
    avg_bbox_width_meters: Optional[float] = None
    median_bbox_width_meters: Optional[float] = None
    std_bbox_width_meters: Optional[float] = None


class TelemetryPayload(BaseModel):
    """Opt-in telemetry payload for a completed job.

    Deliberately excludes input_path/output_dir, filenames, raw log
    events, and full exception messages - see the telemetry privacy spec
    for what's excluded and why. Only ever construct this via
    job_manager.build_telemetry_payload(), never by hand from job.config.
    """

    schema_version: int = 1
    job_id: str
    app_version: Optional[str] = None
    detector_version: Optional[str] = None
    os: str
    device: Optional[str] = None
    status: JobStatus
    error_type: Optional[str] = None
    # When the job began running not when it was submitted - None if it
    # was cancelled while still queued
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    # fisheye's own duration_sec from job_finished: file processing only,
    # excluding model load and UI overhead. None if the job failed since
    # job_finished is only logged on success.
    processing_seconds: Optional[float] = None
    file_count: int
    export_options: List[ExportType]
    upstream_direction: Optional[UpstreamDirectionTypes] = None
    distance_offset: float = 0.0
    counts: List[FileCount]
    track_stats: List[FileTrackStats]


class TelemetryContact(BaseModel):
    """Contact details a user can attach when they choose to be reachable
    about their results. Only email is required."""

    name: Optional[str] = None
    institution: Optional[str] = None
    email: EmailStr


class TelemetrySettings(BaseModel):
    """The user's opt-in telemetry choice, persisted by telemetry_settings.py.

    choice is None until the user has made a choice, which is what tells
    the frontend to show the opt-in dialog - and means nothing is sent.
    """

    choice: Optional[TelemetryChoice] = None
    contact: Optional[TelemetryContact] = None

    @model_validator(mode="after")
    def _contact_only_with_contact_choice(self) -> "TelemetrySettings":
        # Contact details are dropped for any other choice, so switching
        # from "contact" to "anonymous" can never leave them behind to be
        # sent later.
        if self.choice != TelemetryChoice.CONTACT:
            self.contact = None
        elif self.contact is None:
            raise ValueError("contact details are required for the 'contact' choice")
        return self


class TelemetrySettingsRequest(TelemetrySettings):
    """Body for PUT /settings/telemetry. Same as TelemetrySettings except a
    choice is required - "not chosen yet" is only ever the starting state,
    never something a client sets."""

    choice: TelemetryChoice
