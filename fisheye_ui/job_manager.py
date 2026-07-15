import csv
import ctypes
import glob
import queue as _queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
from fisheye.common.system import generate_job_id
from omegaconf import DictConfig, OmegaConf

from fisheye_ui.enums import JobStatus

logger = structlog.get_logger()


def _raise_in_thread(tid: int, exc_type: type) -> None:
    """Inject an exception into a running thread at its next Python bytecode."""
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid), ctypes.py_object(exc_type)
    )
    if res > 1:
        # Rolled back if something went wrong
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)


@dataclass
class Job:
    id: str
    status: JobStatus
    created_at: datetime
    config: Dict[str, Any]
    output_dir: Optional[str] = None
    results: Optional[List] = None
    error: Optional[str] = None
    finished_at: Optional[datetime] = None
    progress_queue: Optional[Any] = field(default=None, repr=False)
    _thread_id: Optional[int] = field(default=None, repr=False)


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(self, config: Union[Dict, DictConfig]) -> str:
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
            progress_queue=_queue.Queue(),
        )
        with self._lock:
            self._jobs[job_id] = job

        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        job._thread_id = t.ident
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def has_active_jobs(self) -> bool:
        """Whether any job is currently pending or running - used by the
        remote-deployment idle-watcher so it never stops the GPU worker
        mid-job, regardless of how long it's been since the last request."""
        return any(
            job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            for job in self._jobs.values()
        )

    def idle_seconds(self) -> Optional[float]:
        """Seconds since the most recent job finished (completed/failed/
        cancelled). None if no job has ever finished on this worker - the
        remote-deployment idle-watcher falls back to measuring from when
        the worker woke up in that case. This (not raw HTTP traffic) is
        the idle-watcher's activity signal: a user composing the form or
        just reading a completed job's results isn't "activity" for
        auto-sleep purposes, only job start/finish is."""
        finished = [job.finished_at for job in self._jobs.values() if job.finished_at]
        if not finished:
            return None
        return (datetime.utcnow() - max(finished)).total_seconds()

    def get_job_queue(self, job_id: str) -> Optional[Any]:
        job = self._jobs.get(job_id)
        return job.progress_queue if job is not None else None

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.utcnow()
        if job._thread_id is not None:
            _raise_in_thread(job._thread_id, SystemExit)
        return True

    def _run(self, job: Job) -> None:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(job_id=job.id)

        input_path = Path(job.config["input_path"])
        # Mirror PipelineRunner._save_summary_csv's fallback: when input_path is
        # itself a directory (batch mode), outputs land in that directory, not
        # its parent
        output_dir = job.config.get("output_dir") or str(
            input_path if input_path.is_dir() else input_path.parent
        )
        job.output_dir = output_dir

        if job.status == JobStatus.CANCELLED:
            return

        from fisheye.common.logging import progress_queue as pq_var
        from fisheye.runner import run_job

        job.status = JobStatus.RUNNING
        try:
            pq_var.set(job.progress_queue)
            run_job(job.config, job_id=job.id, configure_logging=True)
        except (SystemExit, KeyboardInterrupt):
            return  # cancelled via _raise_in_thread
        except Exception as e:
            job.error = str(e)
            job.status = JobStatus.FAILED
            job.finished_at = datetime.utcnow()
            return

        if job.status == JobStatus.CANCELLED:
            return

        job.results = _read_summary_csv(output_dir, job.id)
        if job.results is None:
            job.error = "No files were processed. Output files may already exist in the output directory."
            job.status = JobStatus.FAILED
        else:
            job.status = JobStatus.COMPLETED
        job.finished_at = datetime.utcnow()


def _read_summary_csv(output_dir: str, job_id: str) -> Optional[List[Dict]]:
    matches = glob.glob(str(Path(output_dir) / f"*{job_id}_summary.csv"))
    if not matches:
        return None
    with open(matches[0], newline="") as f:
        return list(csv.DictReader(f))


job_manager = JobManager()
