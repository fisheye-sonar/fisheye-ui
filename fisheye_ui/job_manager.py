import csv
import glob
import multiprocessing
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
from fisheye.common.system import generate_job_id
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
    progress_queue: queue.Queue = field(
        default_factory=lambda: queue.Queue(maxsize=100), repr=False
    )
    _process: Optional[multiprocessing.Process] = field(default=None, repr=False)


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

        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()

        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by its ID."""
        return self._jobs.get(job_id)

    def get_job_queue(self, job_id: str) -> Optional[queue.Queue]:
        job = self._jobs.get(job_id)
        return job.progress_queue if job is not None else None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job by terminating its subprocess."""
        job = self._jobs.get(job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job.status = JobStatus.CANCELLED
        if job._process and job._process.is_alive():
            job._process.terminate()
            job._process.join(timeout=5)
            if job._process.is_alive():
                job._process.kill()
        return True

    def _run(self, job: Job) -> None:
        """Monitor a job subprocess and update status when it finishes."""
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(job_id=job.id)

        output_dir = job.config.get("output_dir") or str(
            Path(job.config["input_path"]).parent
        )
        job.output_dir = output_dir

        if job.status == JobStatus.CANCELLED:
            return

        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()
        process = ctx.Process(
            target=_run_job_subprocess,
            args=(job.config, job.id, result_queue),
            daemon=True,
        )
        job._process = process

        job.status = JobStatus.RUNNING
        process.start()
        process.join()

        if job.status == JobStatus.CANCELLED:
            return

        try:
            success, error = result_queue.get_nowait()
        except queue.Empty:
            job.error = "Job process ended unexpectedly"
            job.status = JobStatus.FAILED
            return

        if success:
            job.results = _read_summary_csv(output_dir, job.id)
            job.status = JobStatus.COMPLETED
        else:
            job.error = error
            job.status = JobStatus.FAILED


def _run_job_subprocess(
    config: dict, job_id: str, result_queue: multiprocessing.Queue
) -> None:
    """Entry point for the job subprocess."""
    try:
        from fisheye.runner import run_job

        run_job(config, job_id=job_id, configure_logging=True)
        result_queue.put((True, None))
    except Exception as e:
        result_queue.put((False, str(e)))


def _read_summary_csv(output_dir: str, job_id: str) -> Optional[List[Dict]]:
    matches = glob.glob(str(Path(output_dir) / f"*{job_id}_summary.csv"))
    if not matches:
        return None
    with open(matches[0], newline="") as f:
        return list(csv.DictReader(f))


job_manager = JobManager()
