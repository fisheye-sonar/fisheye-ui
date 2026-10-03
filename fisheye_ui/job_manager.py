import csv
import ctypes
import glob
import json
import os
import queue as _queue
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
from fisheye.common.system import generate_job_id
from omegaconf import DictConfig, OmegaConf

from fisheye_ui.enums import JobStatus
from fisheye_ui.paths import JOBS_DIR, UPLOAD_DIR
from fisheye_ui.schemas import FileCount, FileTrackStats, TelemetryPayload

logger = structlog.get_logger()

# Limits how many jobs run concurrently. Jobs beyond this remain queued
# (PENDING) until a slot is available. Defaults to 1 since a single shared
# GPU typically performs better with serialized execution. Override with
# FISHEYE_UI_MAX_CONCURRENT_JOBS.
MAX_CONCURRENT_JOBS = int(os.environ.get("FISHEYE_UI_MAX_CONCURRENT_JOBS", "1"))


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
    # Exception class name only (e.g. "FileNotFoundError"), set alongside
    # `error` in _run()'s except block. Kept separate from `error` because
    # the opt-in telemetry payload (see build_telemetry_payload) must never
    # send the full message - it frequently embeds the failing file's path.
    error_type: Optional[str] = None
    finished_at: Optional[datetime] = None
    progress_queue: Optional[Any] = field(default=None, repr=False)
    # Whitelisted structlog events captured during the run (job_started,
    # job_finished, processed_file_stats) - see logging.py's progress
    # router. Used only to build the opt-in telemetry payload; not
    # persisted, not shown in the UI.
    telemetry_events: List[Dict] = field(default_factory=list, repr=False)
    _thread_id: Optional[int] = field(default=None, repr=False)


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        # Guards self._jobs
        self._lock = threading.Lock()
        # Guards writes to persisted job state. Concurrent persists (e.g. job
        # completion and cancellation) can race because they share the same
        # temporary file, causing one write to overwrite the other.
        self._persist_lock = threading.Lock()
        # Bounds how many jobs run their actual pipeline work at once (see
        # MAX_CONCURRENT_JOBS). A job still gets its own thread immediately
        # on creation same as always; past the cap, that thread just blocks
        # here before touching the GPU, so cancelling a queued job still
        # works via the existing _raise_in_thread mechanism.
        self._run_semaphore = threading.Semaphore(MAX_CONCURRENT_JOBS)
        # Tracks uploads streaming to disk (see routes/files.py's
        # upload_file) - no Job exists yet at that point (the job isn't
        # created until the user submits the form after the upload
        # finishes), so has_active_jobs() alone can't see it.
        # _active_uploads gates the idle-watcher's "never stop" check the
        # same way a pending/running job does; _last_upload_finished_at
        # extends idle_seconds' existing grace period to also cover the gap
        # between sequential uploads in a multi-file batch, not just the
        # instant a single upload is actively streaming.
        self._active_uploads = 0
        self._last_upload_finished_at: Optional[datetime] = None
        self._uploads_lock = threading.Lock()
        self._reload_from_disk()

    def upload_started(self) -> None:
        with self._uploads_lock:
            self._active_uploads += 1

    def upload_finished(self) -> None:
        with self._uploads_lock:
            self._active_uploads -= 1
            self._last_upload_finished_at = datetime.utcnow()

    def has_active_uploads(self) -> bool:
        with self._uploads_lock:
            return self._active_uploads > 0

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
        self._persist(job)

        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        job._thread_id = t.ident
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def drop_job(self, job_id: str) -> None:
        """Drop a job from the in-memory registry. Called by routes/files.py's
        sweep once its on-disk record has expired, so a long-running process
        doesn't keep accumulating finished jobs in memory forever."""
        with self._lock:
            self._jobs.pop(job_id, None)

    def _record_path(self, job_id: str) -> Path:
        return JOBS_DIR / f"{job_id}.json"

    def _persist(self, job: Job) -> None:
        """Write job to disk so it survives a process restart. Written
        temp-then-rename so a crash mid-write can never leave a corrupt
        record behind for _reload_from_disk to trip over."""
        try:
            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            record = {
                "id": job.id,
                "status": job.status.value,
                "created_at": job.created_at.isoformat(),
                "config": job.config,
                "output_dir": job.output_dir,
                "results": job.results,
                "error": job.error,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
            tmp_path = self._record_path(job.id).with_suffix(".json.tmp")
            with self._persist_lock:
                with tmp_path.open("w") as f:
                    json.dump(record, f)
                os.replace(tmp_path, self._record_path(job.id))
        except OSError:
            logger.warning("job_persist_failed", job_id=job.id)

    def _reload_from_disk(self) -> None:
        """Restore job records left by a previous process (e.g. before a
        restart), so results stay reachable by job ID without the UI having
        stayed open. A job still PENDING/RUNNING when the process went down
        can't be resumed - its thread is gone - so it's surfaced as failed
        instead of left spinning forever."""
        if not JOBS_DIR.is_dir():
            return
        for path in JOBS_DIR.glob("*.json"):
            try:
                with path.open() as f:
                    record = json.load(f)
                job = Job(
                    id=record["id"],
                    status=JobStatus(record["status"]),
                    created_at=datetime.fromisoformat(record["created_at"]),
                    config=record["config"],
                    output_dir=record.get("output_dir"),
                    results=record.get("results"),
                    error=record.get("error"),
                    finished_at=(
                        datetime.fromisoformat(record["finished_at"])
                        if record.get("finished_at")
                        else None
                    ),
                    progress_queue=_queue.Queue(),
                )
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                logger.warning("job_record_reload_failed", path=str(path))
                continue

            if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                job.status = JobStatus.FAILED
                job.error = "Interrupted by a server restart"
                job.finished_at = datetime.utcnow()
                self._persist(job)

            self._jobs[job.id] = job

    def has_active_jobs(self, exclude_job_id: Optional[str] = None) -> bool:
        """Whether any job (other than exclude_job_id) is currently pending
        or running. Used by the remote-deployment idle-watcher, with no
        exclusion, so it never stops the GPU worker mid-job regardless of
        how long it's been since the last request. Also used by the frontend
        (excluding the job it's currently viewing) to warn that the shared
        GPU is busy with another job."""
        return any(
            job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            for job in self._jobs.values()
            if job.id != exclude_job_id
        )

    def idle_seconds(self) -> Optional[float]:
        """Seconds since the most recent job finished (completed/failed/
        cancelled) or upload completed, whichever is later. None if neither
        has ever happened on this worker - the remote-deployment
        idle-watcher falls back to measuring from when the worker woke up
        in that case. This (not raw HTTP traffic) is the idle-watcher's
        activity signal: a user composing the form or just reading a
        completed job's results isn't "activity" for auto-sleep purposes,
        only job start/finish and upload activity are. Counting upload
        *completion* here (has_active_uploads covers the moment one is
        actively streaming) gives the gap between sequential uploads in a
        multi-file batch the same grace period a finished job gets, rather
        than an instantaneous cutoff the idle-watcher's poll could land in
        the middle of."""
        finished = [job.finished_at for job in self._jobs.values() if job.finished_at]
        with self._uploads_lock:
            if self._last_upload_finished_at:
                finished.append(self._last_upload_finished_at)
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
        self._persist(job)
        if job._thread_id is not None:
            _raise_in_thread(job._thread_id, SystemExit)
        return True

    def active_upload_dirs(self) -> set:
        """Per-job dirs under UPLOAD_DIR that a pending/running job's input
        still lives in - routes/files.py's sweep must not reclaim these out
        from under an in-progress job. Native file-picker inputs (outside
        UPLOAD_DIR) aren't included since the sweep never touches them."""
        dirs = set()
        for job in self._jobs.values():
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                continue
            upload_dir = Path(job.config["input_path"]).parent
            if upload_dir.parent == UPLOAD_DIR:
                dirs.add(upload_dir)
        return dirs

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

        try:
            if job.status == JobStatus.CANCELLED:
                return

            from fisheye.common.logging import progress_queue as pq_var
            from fisheye.runner import run_job

            # Jobs beyond MAX_CONCURRENT_JOBS wait here while remaining PENDING.
            # If cancelled while waiting, the cancellation is handled immediately after
            # acquiring the semaphore, releasing the slot without running the job.
            with self._run_semaphore:
                if job.status == JobStatus.CANCELLED:
                    return

                job.status = JobStatus.RUNNING
                self._persist(job)
                _write_params_json(output_dir, job)
                try:
                    pq_var.set(job.progress_queue)
                    run_job(job.config, job_id=job.id, configure_logging=True)
                except (SystemExit, KeyboardInterrupt):
                    return  # cancelled via _raise_in_thread
                except Exception as e:
                    job.error = str(e)
                    job.error_type = type(e).__name__
                    job.status = JobStatus.FAILED
                    job.finished_at = datetime.utcnow()
                    self._persist(job)
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
                self._persist(job)
        finally:
            _cleanup_upload_input(job)


def _write_params_json(output_dir: str, job: Job) -> None:
    """Write the parameters used per job, so results stay traceable to the
    settings that produced them without having to keep the UI open.
    Written before run_job starts so it's there even if the job later fails."""
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(output_dir) / f"{job.id}_params.json"
        with dest.open("w") as f:
            json.dump(job.config, f, indent=2)
    except OSError:
        logger.warning("params_json_write_failed", output_dir=output_dir)


def _cleanup_upload_input(job: Job) -> None:
    """Delete a job's raw input file once the job is done with it. Only
    touches files under UPLOAD_DIR (i.e. uploaded via /files/upload) - a
    native file-picker path on the user's own machine is left alone. Also
    removes the per-job upload dir if that leaves it empty; if outputs
    landed there too (output_dir wasn't overridden), the rmdir fails and
    routes/files.py's sweep reclaims it later once results have been
    downloaded."""
    input_path = Path(job.config["input_path"])
    upload_dir = input_path.parent
    if upload_dir.parent != UPLOAD_DIR:
        return
    try:
        input_path.unlink(missing_ok=True)
        upload_dir.rmdir()
    except OSError:
        pass


def _read_summary_csv(output_dir: str, job_id: str) -> Optional[List[Dict]]:
    matches = glob.glob(str(Path(output_dir) / f"*{job_id}_summary.csv"))
    if not matches:
        return None
    with open(matches[0], newline="") as f:
        return list(csv.DictReader(f))


def build_telemetry_payload(job: Job) -> TelemetryPayload:
    """Opt-in telemetry payload for a job.

    Deliberately never reads job.config's input_path/output_dir, or any
    filename field from job.results (e.g. summary CSV's Source.Name) -
    see the telemetry privacy spec for what's excluded and why.

    counts and track_stats are joined on file_index. If a source doesn't
    carry a real file_index (an older `fisheye` without the upstream
    per-file-key fix), that source's entries are left out entirely rather
    than guessed at by row/event position (a wrong join is worse than a
    missing one).
    """
    counts = []
    for row in job.results or []:
        file_index = row.get("file_index")
        if file_index in (None, "", "nan"):
            continue
        counts.append(
            FileCount(
                file_index=int(float(file_index)),
                absolute_up=int(float(row.get("absolute_up") or 0)),
                absolute_down=int(float(row.get("absolute_down") or 0)),
                net_count=int(float(row.get("net_count") or 0)),
            )
        )

    track_stats = []
    for event in job.telemetry_events:
        if event.get("event") != "processed_file_stats":
            continue
        file_index = event.get("file_index")
        if file_index is None:
            continue
        track_stats.append(
            FileTrackStats(
                file_index=file_index,
                num_tracks=event.get("num_tracks", 0),
                num_counts=event.get("num_counts", 0),
                avg_bbox_width_meters=event.get("avg_bbox_width_meters"),
                median_bbox_width_meters=event.get("median_bbox_width_meters"),
                std_bbox_width_meters=event.get("std_bbox_width_meters"),
            )
        )

    job_started = next(
        (e for e in job.telemetry_events if e.get("event") == "job_started"), {}
    )
    job_finished = next(
        (e for e in job.telemetry_events if e.get("event") == "job_finished"), {}
    )
    platform_cfg = (job.config or {}).get("platform") or {}

    return TelemetryPayload(
        job_id=job.id,
        app_version=job_started.get("app_version") or job_finished.get("app_version"),
        detector_version=job_started.get("detector_version"),
        os=sys.platform,
        device=platform_cfg.get("device"),
        status=job.status,
        error_type=job.error_type,
        started_at=job.created_at,
        finished_at=job.finished_at,
        duration_seconds=(
            (job.finished_at - job.created_at).total_seconds()
            if job.finished_at
            else None
        ),
        file_count=len(job.results or []),
        export_options=(job.config or {}).get("export_options", []),
        upstream_direction=(job.config or {}).get("upstream_direction"),
        distance_offset=(job.config or {}).get("distance_offset", 0.0),
        counts=counts,
        track_stats=track_stats,
    )


job_manager = JobManager()
