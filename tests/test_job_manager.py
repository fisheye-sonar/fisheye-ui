import time
from datetime import datetime
from pathlib import Path

import pytest

from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, JobManager, _read_summary_csv


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
    def _wait_for_terminal_status(self, manager, job_id, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = manager.get_job(job_id)
            if job.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                return job
            time.sleep(0.01)
        raise AssertionError(f"job did not reach a terminal status within {timeout}s")

    def test_successful_run_populates_results(self, tmp_path, monkeypatch):
        def fake_run_job(config, job_id, configure_logging=True):
            out = Path(config["output_dir"]) / f"clip_{job_id}_summary.csv"
            out.write_text("absolute_up,absolute_down,net_count\n3,1,2\n")

        monkeypatch.setattr("fisheye.runner.run_job", fake_run_job)

        manager = JobManager()
        job_id = manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path)}
        )
        job = self._wait_for_terminal_status(manager, job_id)

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
        job = self._wait_for_terminal_status(manager, job_id)

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
        job = self._wait_for_terminal_status(manager, job_id)

        assert job.status == JobStatus.FAILED
        assert job.error == "boom"
