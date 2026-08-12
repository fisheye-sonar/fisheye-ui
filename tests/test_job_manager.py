import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from fisheye_ui import job_manager as job_manager_module
from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, JobManager, _read_summary_csv


def _wait_for_terminal_status(manager, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach a terminal status within {timeout}s")


def _wait_until(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


class TestReadSummaryCsv:
    def test_returns_none_when_no_matching_file(self, tmp_path):
        assert _read_summary_csv(str(tmp_path), "job-123") is None

    def test_reads_rows_from_matching_file(self, tmp_path):
        (tmp_path / "clipA_job-123_summary.csv").write_text(
            "absolute_up,absolute_down,net_count\n3,1,2\n"
        )
        rows = _read_summary_csv(str(tmp_path), "job-123")
        assert rows == [{"absolute_up": "3", "absolute_down": "1", "net_count": "2"}]

    def test_ignores_files_for_other_job_ids(self, tmp_path):
        (tmp_path / "clipA_other-job_summary.csv").write_text("a\n1\n")
        assert _read_summary_csv(str(tmp_path), "job-123") is None


class TestCancelJob:
    def test_unknown_job_id_returns_false(self):
        manager = JobManager()
        assert manager.cancel_job("does-not-exist") is False

    @pytest.mark.parametrize(
        "status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
    )
    def test_non_cancellable_status_returns_false(self, status):
        manager = JobManager()
        job = Job(
            id="job-123", status=status, created_at=datetime(2026, 1, 1), config={}
        )
        manager._jobs["job-123"] = job
        assert manager.cancel_job("job-123") is False
        assert job.status == status

    @pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
    def test_cancellable_status_is_cancelled(self, status):
        manager = JobManager()
        job = Job(
            id="job-123", status=status, created_at=datetime(2026, 1, 1), config={}
        )
        manager._jobs["job-123"] = job
        assert manager.cancel_job("job-123") is True
        assert job.status == JobStatus.CANCELLED


class TestCreateJob:
    def test_successful_run_populates_results(self, tmp_path, monkeypatch):
        def fake_run_job(config, job_id, configure_logging=True):
            out = Path(config["output_dir"]) / f"clip_{job_id}_summary.csv"
            out.write_text("absolute_up,absolute_down,net_count\n3,1,2\n")

        monkeypatch.setattr("fisheye.runner.run_job", fake_run_job)

        manager = JobManager()
        job_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path)}
        )
        job = _wait_for_terminal_status(manager, job_id)

        assert job.status == JobStatus.COMPLETED
        assert job.results == [
            {"absolute_up": "3", "absolute_down": "1", "net_count": "2"}
        ]
        assert job.error is None

    def test_no_summary_csv_marks_job_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            lambda config, job_id, configure_logging=True: None,
        )

        manager = JobManager()
        job_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path)}
        )
        job = _wait_for_terminal_status(manager, job_id)

        assert job.status == JobStatus.FAILED
        assert job.error is not None

    def test_exception_in_pipeline_marks_job_failed(self, tmp_path, monkeypatch):
        def raising_run_job(config, job_id, configure_logging=True):
            raise ValueError("boom")

        monkeypatch.setattr("fisheye.runner.run_job", raising_run_job)

        manager = JobManager()
        job_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path)}
        )
        job = _wait_for_terminal_status(manager, job_id)

        assert job.status == JobStatus.FAILED
        assert job.error == "boom"


class TestHasActiveJobsAndIdleSeconds:
    def test_no_jobs_is_not_active_and_idle_is_none(self):
        manager = JobManager()
        assert manager.has_active_jobs() is False
        assert manager.idle_seconds() is None

    @pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
    def test_pending_or_running_job_is_active(self, status):
        manager = JobManager()
        manager._jobs["job-123"] = Job(
            id="job-123", status=status, created_at=datetime(2026, 1, 1), config={}
        )
        assert manager.has_active_jobs() is True

    def test_exclude_job_id_ignores_that_job(self):
        manager = JobManager()
        manager._jobs["job-123"] = Job(
            id="job-123",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={},
        )
        assert manager.has_active_jobs(exclude_job_id="job-123") is False

    def test_idle_seconds_measures_from_most_recent_finish(self):
        manager = JobManager()
        manager._jobs["older"] = Job(
            id="older",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={},
            finished_at=datetime.utcnow(),
        )
        manager._jobs["still-running"] = Job(
            id="still-running",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={},
        )
        idle = manager.idle_seconds()
        assert idle is not None
        assert idle < 5

    def test_upload_in_progress_has_no_active_jobs_but_is_tracked_separately(self):
        manager = JobManager()
        manager.upload_started()
        assert manager.has_active_jobs() is False
        assert manager.has_active_uploads() is True

    def test_upload_finished_clears_active_uploads(self):
        manager = JobManager()
        manager.upload_started()
        manager.upload_finished()
        assert manager.has_active_uploads() is False

    def test_second_concurrent_upload_keeps_active_uploads_true_after_first_finishes(
        self,
    ):
        manager = JobManager()
        manager.upload_started()
        manager.upload_started()
        manager.upload_finished()
        assert manager.has_active_uploads() is True

    def test_idle_seconds_measures_from_most_recent_upload_finish(self):
        manager = JobManager()
        manager._jobs["older"] = Job(
            id="older",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={},
            finished_at=datetime(2026, 1, 1),
        )
        manager.upload_started()
        manager.upload_finished()
        idle = manager.idle_seconds()
        assert idle is not None
        assert idle < 5


class TestActiveUploadDirs:
    def test_includes_pending_job_input_under_upload_dir(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        job_subdir = upload_dir / "abc123"
        manager = JobManager()
        manager._jobs["job-1"] = Job(
            id="job-1",
            status=JobStatus.PENDING,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(job_subdir / "clip.aris")},
        )
        assert manager.active_upload_dirs() == {job_subdir}

    def test_excludes_input_outside_upload_dir(self, tmp_path):
        manager = JobManager()
        manager._jobs["job-1"] = Job(
            id="job-1",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(tmp_path / "elsewhere" / "clip.aris")},
        )
        assert manager.active_upload_dirs() == set()

    def test_excludes_terminal_job(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        manager = JobManager()
        manager._jobs["job-1"] = Job(
            id="job-1",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(upload_dir / "abc123" / "clip.aris")},
        )
        assert manager.active_upload_dirs() == set()


class TestPersistAndReload:
    def test_round_trips_job_to_disk(self, isolated_dirs):
        manager = JobManager()
        job = Job(
            id="job-123",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={"input_path": "/a/b.aris"},
            output_dir="/tmp/out",
            results=[{"absolute_up": "3"}],
        )
        manager._persist(job)

        reloaded = JobManager()
        restored = reloaded.get_job("job-123")
        assert restored is not None
        assert restored.status == JobStatus.COMPLETED
        assert restored.output_dir == "/tmp/out"
        assert restored.results == [{"absolute_up": "3"}]

    @pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
    def test_interrupted_job_is_marked_failed_on_reload(self, isolated_dirs, status):
        manager = JobManager()
        job = Job(
            id="job-123",
            status=status,
            created_at=datetime(2026, 1, 1),
            config={},
        )
        manager._persist(job)

        reloaded = JobManager()
        restored = reloaded.get_job("job-123")
        assert restored.status == JobStatus.FAILED
        assert restored.error == "Interrupted by a server restart"

    def test_terminal_job_status_is_preserved_on_reload(self, isolated_dirs):
        manager = JobManager()
        job = Job(
            id="job-123",
            status=JobStatus.CANCELLED,
            created_at=datetime(2026, 1, 1),
            config={},
            finished_at=datetime.utcnow(),
        )
        manager._persist(job)

        reloaded = JobManager()
        assert reloaded.get_job("job-123").status == JobStatus.CANCELLED

    def test_corrupt_record_is_skipped_not_fatal(self, isolated_dirs):
        jobs_dir = isolated_dirs["jobs_dir"]
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "broken.json").write_text("{not valid json")

        reloaded = JobManager()
        assert reloaded.get_job("broken") is None

    def test_persist_writes_via_tmp_then_rename(self, isolated_dirs):
        manager = JobManager()
        job = Job(
            id="job-123",
            status=JobStatus.PENDING,
            created_at=datetime(2026, 1, 1),
            config={},
        )
        manager._persist(job)

        jobs_dir = isolated_dirs["jobs_dir"]
        assert (jobs_dir / "job-123.json").exists()
        assert not (jobs_dir / "job-123.json.tmp").exists()
        record = json.loads((jobs_dir / "job-123.json").read_text())
        assert record["id"] == "job-123"
        assert record["status"] == "pending"


class TestWriteParamsJson:
    def test_writes_config_before_run_completes(self, tmp_path):
        job = Job(
            id="job-123",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={"input_path": "/a.aris", "platform": {"device": "cpu"}},
        )
        job_manager_module._write_params_json(str(tmp_path), job)

        written = json.loads((tmp_path / "job-123_params.json").read_text())
        assert written == job.config


class TestCleanupUploadInput:
    def test_removes_input_and_empty_upload_dir(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        job_subdir = upload_dir / "abc123"
        job_subdir.mkdir(parents=True)
        input_file = job_subdir / "clip.aris"
        input_file.write_text("data")

        job = Job(
            id="job-1",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(input_file)},
        )
        job_manager_module._cleanup_upload_input(job)

        assert not input_file.exists()
        assert not job_subdir.exists()

    def test_leaves_output_in_place_when_dir_not_empty(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        job_subdir = upload_dir / "abc123"
        job_subdir.mkdir(parents=True)
        input_file = job_subdir / "clip.aris"
        input_file.write_text("data")
        (job_subdir / "clip_job-1_summary.csv").write_text("data")

        job = Job(
            id="job-1",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(input_file)},
        )
        job_manager_module._cleanup_upload_input(job)

        assert not input_file.exists()
        assert job_subdir.exists()  # rmdir failed because it's non-empty

    def test_ignores_input_outside_upload_dir(self, tmp_path):
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")

        job = Job(
            id="job-1",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(input_file)},
        )
        job_manager_module._cleanup_upload_input(job)

        assert input_file.exists()


class TestConcurrency:
    def _blocking_run_job(self, started_event, release_event):
        def fake_run_job(config, job_id, configure_logging=True):
            started_event.set()
            release_event.wait(timeout=5)
            out = Path(config["output_dir"]) / f"clip_{job_id}_summary.csv"
            out.write_text("absolute_up,absolute_down,net_count\n1,0,1\n")

        return fake_run_job

    def test_second_job_stays_pending_until_slot_frees(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job_manager_module, "MAX_CONCURRENT_JOBS", 1)
        started_event = threading.Event()
        release_event = threading.Event()
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            self._blocking_run_job(started_event, release_event),
        )

        manager = JobManager()
        job1_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path / "out1")}
        )
        assert started_event.wait(timeout=5)

        job2_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path / "out2")}
        )
        # Give job2's thread a moment to reach (and block on) the semaphore.
        time.sleep(0.2)
        assert manager.get_job(job2_id).status == JobStatus.PENDING

        release_event.set()
        job1 = _wait_for_terminal_status(manager, job1_id)
        assert job1.status == JobStatus.COMPLETED

        job2 = _wait_for_terminal_status(manager, job2_id)
        assert job2.status == JobStatus.COMPLETED

    def test_queued_job_can_be_cancelled_before_it_starts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job_manager_module, "MAX_CONCURRENT_JOBS", 1)
        started_event = threading.Event()
        release_event = threading.Event()
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            self._blocking_run_job(started_event, release_event),
        )

        manager = JobManager()
        job1_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path / "out1")}
        )
        assert started_event.wait(timeout=5)

        job2_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path / "out2")}
        )
        _wait_until(lambda: manager.get_job(job2_id).status == JobStatus.PENDING)

        assert manager.cancel_job(job2_id) is True
        assert manager.get_job(job2_id).status == JobStatus.CANCELLED

        release_event.set()
        job1 = _wait_for_terminal_status(manager, job1_id)
        assert job1.status == JobStatus.COMPLETED
        # job2 never actually ran, so it must stay CANCELLED rather than
        # being overwritten once its thread wakes up and acquires the slot.
        time.sleep(0.2)
        assert manager.get_job(job2_id).status == JobStatus.CANCELLED
