from enum import Enum


class JobStatus(str, Enum):
    """Enum for job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TelemetryChoice(str, Enum):
    """The user's opt-in telemetry choice."""

    OFF = "off"
    ANONYMOUS = "anonymous"
    CONTACT = "contact"
