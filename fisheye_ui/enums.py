from enum import Enum


class JobStatus(str, Enum):
    """Enum for job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
