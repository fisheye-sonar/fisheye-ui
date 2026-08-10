import queue
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from fisheye_ui import job_manager as job_manager_module
from fisheye_ui import usage as usage_module
from fisheye_ui.app import app
from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, job_manager
from fisheye_ui.routes import files as files_module


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_job_registry():
    """job_manager is a process-wide singleton — clear it around each test
    so jobs seeded/created by one test can't leak into another."""
    job_manager._jobs.clear()
    yield
    job_manager._jobs.clear()


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect JOBS_DIR/UPLOAD_DIR (persisted job records, uploaded input
    files) to a per-test tmp_path, so tests never read/write the real system
    temp dir - both job_manager.py and routes/files.py import these names
    directly, so each binding needs patching separately."""
    jobs_dir = tmp_path / "fisheye-ui-jobs"
    upload_dir = tmp_path / "fisheye-ui-uploads"
    monkeypatch.setattr(job_manager_module, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(job_manager_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(files_module, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(files_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(usage_module, "USAGE_PATH", tmp_path / "fisheye-ui-usage.json")
    return {"jobs_dir": jobs_dir, "upload_dir": upload_dir}


@pytest.fixture
def make_job():
    def _make_job(**overrides):
        defaults = dict(
            id="job-123",
            status=JobStatus.PENDING,
            created_at=datetime(2026, 1, 1),
            config={},
            progress_queue=queue.Queue(),
        )
        defaults.update(overrides)
        job = Job(**defaults)
        job_manager._jobs[job.id] = job
        return job

    return _make_job
