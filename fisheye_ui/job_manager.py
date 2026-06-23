import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fisheye.common.system import generate_job_id
from fisheye.runner import run_job
from omegaconf import DictConfig, OmegaConf

from fisheye_ui.enums import JobStatus


@dataclass
class Job:
    """Job class."""

    id: str
    status: JobStatus
    created_at: datetime
    config: Dict[str, Any]
    output_dir: Optional[str] = None
    results: Optional[List] = None
    error: Optional[str] = None
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


class JobManager:
    """Job manager class."""

    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(self, config: Union[Dict, DictConfig]) -> str:
        """Create a new job."""
        if isinstance(config, DictConfig):
            config_dict = OmegaConf.to_container(config, resolve=True)
        else:
            config_dict = config

        job_id = generate_job_id()
        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            config=config_dict,
            output_dir=config_dict.get("output_dir"),
        )

        # avoid race condition
        with self._lock:
            self._jobs[job_id] = job

        # start job in a separate thread so that it doesn't block the server from shutting down
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        job._thread = thread
        thread.start()

        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by its ID."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job by its ID. Will cancel job once current one complete."""
        job = self._jobs.get(job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job._cancel_event.set()
        job.status = JobStatus.CANCELLED
        return True

    def _run(self, job: Job) -> None:
        """Run the job."""
        if job._cancel_event.is_set():
            return

        job.status = JobStatus.RUNNING
        try:
            results = run_job(job.config, job_id=job.id)
            if job._cancel_event.is_set():
                job.status = JobStatus.CANCELLED
            else:
                job.results = results
                job.status = JobStatus.COMPLETED

        except Exception as e:
            if not job._cancel_event.is_set():
                job.error = str(e)
                job.status = JobStatus.FAILED


job_manager = JobManager()
