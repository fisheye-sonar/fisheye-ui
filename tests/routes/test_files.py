import asyncio
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from fisheye_ui.enums import JobStatus
from fisheye_ui.job_manager import Job, job_manager
from fisheye_ui.routes import files as files_module


class TestUploadFile:
    def test_rejects_disallowed_extension(self, client):
        res = client.post("/files/upload?filename=clip.mp4", content=b"data")
        assert res.status_code == 400

    def test_accepts_aris_and_writes_bytes(self, client, isolated_dirs):
        res = client.post("/files/upload?filename=clip.aris", content=b"binary-payload")
        assert res.status_code == 201
        path = Path(res.json()["path"])
        assert path.read_bytes() == b"binary-payload"
        assert path.parent.parent == isolated_dirs["upload_dir"]

    def test_accepts_ddf(self, client):
        res = client.post("/files/upload?filename=clip.ddf", content=b"data")
        assert res.status_code == 201

    def test_active_uploads_is_balanced_after_completion(self, client):
        # Guards against upload_started/upload_finished drifting out of a
        # try/finally pairing and leaking a permanently "active" upload,
        # which would stop the idle-watcher from ever sleeping the worker.
        res = client.post("/files/upload?filename=clip.aris", content=b"data")
        assert res.status_code == 201
        assert job_manager.has_active_uploads() is False


class TestSweepStaleUploads:
    def _make_stale(self, path):
        path.mkdir(parents=True)
        old_time = time.time() - files_module.UPLOAD_MAX_AGE_SECONDS - 3600
        os.utime(path, (old_time, old_time))

    def test_removes_dirs_older_than_max_age(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        upload_dir.mkdir(parents=True)
        stale = upload_dir / "stale"
        self._make_stale(stale)
        fresh = upload_dir / "fresh"
        fresh.mkdir()

        files_module._sweep_stale_uploads()

        assert not stale.exists()
        assert fresh.exists()

    def test_skips_dirs_still_in_use_by_active_job(self, isolated_dirs):
        upload_dir = isolated_dirs["upload_dir"]
        upload_dir.mkdir(parents=True)
        in_use = upload_dir / "in-use"
        self._make_stale(in_use)

        job_manager._jobs["job-1"] = Job(
            id="job-1",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={"input_path": str(in_use / "clip.aris")},
        )

        files_module._sweep_stale_uploads()

        assert in_use.exists()

    def test_noop_when_upload_dir_missing(self, isolated_dirs):
        files_module._sweep_stale_uploads()  # must not raise


class TestSweepStaleJobRecords:
    def _make_stale(self, path):
        path.write_text("{}")
        old_time = time.time() - files_module.UPLOAD_MAX_AGE_SECONDS - 3600
        os.utime(path, (old_time, old_time))

    def test_removes_stale_terminal_record(self, isolated_dirs):
        jobs_dir = isolated_dirs["jobs_dir"]
        jobs_dir.mkdir(parents=True)
        record = jobs_dir / "job-1.json"
        self._make_stale(record)

        files_module._sweep_stale_job_records()

        assert not record.exists()

    def test_keeps_record_for_still_running_job_even_if_old(self, isolated_dirs):
        jobs_dir = isolated_dirs["jobs_dir"]
        jobs_dir.mkdir(parents=True)
        record = jobs_dir / "job-1.json"
        self._make_stale(record)

        job_manager._jobs["job-1"] = Job(
            id="job-1",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
            config={},
        )

        files_module._sweep_stale_job_records()

        assert record.exists()

    def test_removes_orphaned_tmp_file(self, isolated_dirs):
        jobs_dir = isolated_dirs["jobs_dir"]
        jobs_dir.mkdir(parents=True)
        tmp_file = jobs_dir / "job-1.json.tmp"
        self._make_stale(tmp_file)

        files_module._sweep_stale_job_records()

        assert not tmp_file.exists()


class TestRunPicker:
    def test_returns_stripped_stdout_on_success(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 0, stdout="/a/b.aris\n", stderr=""
            ),
        )
        result = asyncio.run(files_module._run_picker("some-applescript"))
        assert result == "/a/b.aris"

    def test_returns_none_when_user_cancels(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 1, stdout="", stderr=""
            ),
        )
        result = asyncio.run(files_module._run_picker("some-applescript"))
        assert result is None


class TestPickFileLinux:
    def test_returns_stdout_on_success(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 0, stdout="/a/b.aris\n", stderr=""
            ),
        )
        assert files_module._pick_file_linux() == "/a/b.aris"

    def test_returns_none_on_cancel(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 1, stdout="", stderr=""
            ),
        )
        assert files_module._pick_file_linux() is None


class TestPickDirectoryLinux:
    def test_returns_stdout_on_success(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 0, stdout="/a/folder\n", stderr=""
            ),
        )
        assert files_module._pick_directory_linux() == "/a/folder"

    def test_returns_none_on_cancel(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, capture_output, text: subprocess.CompletedProcess(
                args, 1, stdout="", stderr=""
            ),
        )
        assert files_module._pick_directory_linux() is None
