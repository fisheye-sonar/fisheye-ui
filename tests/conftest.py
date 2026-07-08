from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from fisheye_ui.app import app
from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, job_manager


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_job_registry():
    """job_manager is a process-wide singleton — clear it around each test
    so jobs seeded by one test can't leak into another."""
    job_manager._jobs.clear()
    yield
    job_manager._jobs.clear()


@pytest.fixture
def make_job():
    def _make_job(**overrides):
        defaults = dict(
            id="job-123",
            status=JobStatus.PENDING,
            created_at=datetime(2026, 1, 1),
            config={},
        )
        defaults.update(overrides)
        job = Job(**defaults)
        job_manager._jobs[job.id] = job
        return job

    return _make_job
