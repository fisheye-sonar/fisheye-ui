import csv
import glob
import multiprocessing
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import structlog
from fisheye.common.system import generate_job_id
from omegaconf import DictConfig, OmegaConf

from fisheye_ui.enums import JobStatus

_MP_CTX = multiprocessing.get_context("spawn")


def _worker_loop(req_q: multiprocessing.Queue) -> None:
    """Imports fisheye/torch once, then runs jobs sequentially from req_q."""
    from fisheye.common.logging import progress_queue as pq_var
    from fisheye.runner import run_job

    while True:
        item = req_q.get()
        if item is None:
            break
        config, job_id, result_q, progress_q = item
        try:
            pq_var.set(progress_q)
            run_job(config, job_id=job_id, configure_logging=True)
            result_q.put((True, None))
        except Exception as e:
            result_q.put((False, str(e)))


class _WorkerPool:
    """
    Single persistent subprocess. Imports fisheye/torch once at startup so
    subsequent jobs pay no subprocess-startup cost.

    After cancellation the worker is terminated and restarted in the background,
    so the next job is ready to run immediately.
    """

    def __init__(self) -> None:
        self._process: Optional[multiprocessing.Process] = None
        self._req_q: Optional[multiprocessing.Queue] = None
        self._lock = threading.Lock()

    def _start_locked(self) -> None:
        """Spawn a fresh worker. Must be called with _lock held."""
        self._req_q = _MP_CTX.Queue()
        self._process = _MP_CTX.Process(
            target=_worker_loop, args=(self._req_q,), daemon=True
        )
        self._process.start()

    def warmup(self) -> None:
        """Ensure a worker is alive (blocking). Call at server startup."""
        with self._lock:
            if not (self._process and self._process.is_alive()):
                self._start_locked()

    def warmup_in_background(self) -> None:
        threading.Thread(target=self.warmup, daemon=True).start()

    def submit(
        self,
        config: dict,
        job_id: str,
        result_q: multiprocessing.Queue,
        progress_q: multiprocessing.Queue,
        cancelled_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Send a job to the worker. Atomically checks cancelled_check while holding
        the lock so a concurrent cancel cannot slip between the liveness check and
        the put().
        """
        with self._lock:
            if cancelled_check and cancelled_check():
                return
            if not (self._process and self._process.is_alive()):
                self._start_locked()
            self._req_q.put((config, job_id, result_q, progress_q))

    def is_alive(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.is_alive()

    def terminate(self) -> None:
        """Kill the worker. Does not restart — callers handle that."""
        with self._lock:
            if self._process and self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=5)
                if self._process.is_alive():
                    self._process.kill()
            self._process = None
            self._req_q = None


_worker_pool = _WorkerPool()


@dataclass
class Job:
    id: str
    status: JobStatus
    created_at: datetime
    config: Dict[str, Any]
    output_dir: Optional[str] = None
    results: Optional[List] = None
    error: Optional[str] = None
    progress_queue: Optional[Any] = field(default=None, repr=False)


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
            progress_queue=_MP_CTX.Queue(maxsize=100),
        )
        with self._lock:
            self._jobs[job_id] = job

        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def get_job_queue(self, job_id: str) -> Optional[Any]:
        job = self._jobs.get(job_id)
        return job.progress_queue if job is not None else None

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job.status = JobStatus.CANCELLED
        _worker_pool.terminate()
        return True

    def _run(self, job: Job) -> None:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(job_id=job.id)

        output_dir = job.config.get("output_dir") or str(
            Path(job.config["input_path"]).parent
        )
        job.output_dir = output_dir

        if job.status == JobStatus.CANCELLED:
            return

        result_queue = _MP_CTX.Queue()
        job.status = JobStatus.RUNNING
        _worker_pool.submit(
            job.config,
            job.id,
            result_queue,
            job.progress_queue,
            cancelled_check=lambda: job.status == JobStatus.CANCELLED,
        )

        while True:
            try:
                success, error = result_queue.get(timeout=1.0)
                break
            except queue.Empty:
                if job.status == JobStatus.CANCELLED:
                    _worker_pool.warmup_in_background()
                    return
                if not _worker_pool.is_alive():
                    job.error = "Job process ended unexpectedly"
                    job.status = JobStatus.FAILED
                    _worker_pool.warmup_in_background()
                    return

        if job.status == JobStatus.CANCELLED:
            return

        if success:
            job.results = _read_summary_csv(output_dir, job.id)
            if job.results is None:
                job.error = "No files were processed. Output files may already exist in the output directory."
                job.status = JobStatus.FAILED
            else:
                job.status = JobStatus.COMPLETED
        else:
            job.error = error
            job.status = JobStatus.FAILED


def _read_summary_csv(output_dir: str, job_id: str) -> Optional[List[Dict]]:
    matches = glob.glob(str(Path(output_dir) / f"*{job_id}_summary.csv"))
    if not matches:
        return None
    with open(matches[0], newline="") as f:
        return list(csv.DictReader(f))


job_manager = JobManager()
