import json
import time
import zipfile
from io import BytesIO

import pytest
from starlette.websockets import WebSocketDisconnect

from fisheye_ui.enums import JobStatus


def _wait_for_terminal_status(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach a terminal status within {timeout}s")


def _job_body(input_path, **overrides):
    body = {
        "input_path": str(input_path),
        "platform": {"model": {"device": "cpu"}},
    }
    body.update(overrides)
    return body


class TestCreateJob:
    def test_success_defaults_output_dir_to_input_parent(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            lambda config, job_id, configure_logging=True: None,
        )
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")

        res = client.post("/jobs", json=_job_body(input_file))
        assert res.status_code == 201
        body = res.json()
        assert body["output_dir"] == str(tmp_path)
        assert body["id"]

    def test_success_with_directory_input_uses_dir_as_output(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            lambda config, job_id, configure_logging=True: None,
        )
        input_dir = tmp_path / "batch"
        input_dir.mkdir()

        res = client.post("/jobs", json=_job_body(input_dir))
        assert res.status_code == 201
        assert res.json()["output_dir"] == str(input_dir)

    def test_explicit_output_dir_is_respected(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            lambda config, job_id, configure_logging=True: None,
        )
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")
        output_dir = tmp_path / "custom-out"

        res = client.post(
            "/jobs", json=_job_body(input_file, output_dir=str(output_dir))
        )
        assert res.status_code == 201
        assert res.json()["output_dir"] == str(output_dir)

    def test_existing_predictions_returns_409_with_suggestion(self, client, tmp_path):
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")
        (tmp_path / "FCe_clip_ID_.txt").write_text("marker")

        res = client.post("/jobs", json=_job_body(input_file))
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert detail["existing_output_dir"] == str(tmp_path)
        assert detail["suggested_output_dir"].startswith(str(tmp_path))
        assert detail["suggested_output_dir"] != str(tmp_path)

    def test_confirm_rerun_writes_to_suggested_dir(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "fisheye.runner.run_job",
            lambda config, job_id, configure_logging=True: None,
        )
        input_file = tmp_path / "clip.aris"
        input_file.write_text("data")
        (tmp_path / "FCe_clip_ID_.txt").write_text("marker")

        first = client.post("/jobs", json=_job_body(input_file))
        suggested = first.json()["detail"]["suggested_output_dir"]

        res = client.post("/jobs", json=_job_body(input_file, confirm_rerun=True))
        assert res.status_code == 201
        assert res.json()["output_dir"] == suggested


class TestGetJob:
    def test_not_found_returns_404(self, client):
        res = client.get("/jobs/does-not-exist")
        assert res.status_code == 404

    def test_found_returns_job_fields(self, client, make_job):
        make_job(
            id="job-123",
            status=JobStatus.COMPLETED,
            output_dir="/tmp/out",
            results=[{"absolute_up": "3"}],
        )
        res = client.get("/jobs/job-123")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == "job-123"
        assert body["status"] == "completed"
        assert body["output_dir"] == "/tmp/out"
        assert body["results"] == [{"absolute_up": "3"}]


class TestCancelJob:
    def test_not_found_returns_404(self, client):
        res = client.delete("/jobs/does-not-exist")
        assert res.status_code == 404

    def test_pending_job_is_cancelled(self, client, make_job):
        job = make_job(id="job-123", status=JobStatus.PENDING)
        res = client.delete("/jobs/job-123")
        assert res.status_code == 204
        assert job.status == JobStatus.CANCELLED

    def test_running_job_is_cancelled(self, client, make_job):
        job = make_job(id="job-123", status=JobStatus.RUNNING)
        res = client.delete("/jobs/job-123")
        assert res.status_code == 204
        assert job.status == JobStatus.CANCELLED

    def test_already_completed_job_returns_404(self, client, make_job):
        job = make_job(id="job-123", status=JobStatus.COMPLETED)
        res = client.delete("/jobs/job-123")
        assert res.status_code == 404
        assert job.status == JobStatus.COMPLETED


class TestGetActive:
    def test_no_jobs_reports_inactive(self, client):
        res = client.get("/jobs/active")
        assert res.status_code == 200
        body = res.json()
        assert body["active"] is False
        assert body["idle_seconds"] is None

    def test_running_job_reports_active(self, client, make_job):
        make_job(id="job-123", status=JobStatus.RUNNING)
        res = client.get("/jobs/active")
        assert res.json()["active"] is True

    def test_exclude_job_id_ignores_that_job(self, client, make_job):
        make_job(id="job-123", status=JobStatus.RUNNING)
        res = client.get("/jobs/active", params={"exclude_job_id": "job-123"})
        assert res.json()["active"] is False


class TestListOutputs:
    def test_job_not_found_returns_404(self, client):
        res = client.get("/jobs/does-not-exist/outputs")
        assert res.status_code == 404

    def test_no_output_dir_returns_empty_list(self, client, make_job):
        make_job(id="job-123", output_dir=None)
        res = client.get("/jobs/job-123/outputs")
        assert res.status_code == 200
        assert res.json() == {"files": []}

    def test_missing_output_dir_returns_empty_list(self, client, make_job, tmp_path):
        make_job(id="job-123", output_dir=str(tmp_path / "does-not-exist"))
        res = client.get("/jobs/job-123/outputs")
        assert res.status_code == 200
        assert res.json() == {"files": []}

    def test_lists_files_including_nested_ones(self, client, make_job, tmp_path):
        (tmp_path / "summary.csv").write_text("a,b\n1,2\n")
        nested = tmp_path / "clipA"
        nested.mkdir()
        (nested / "detail.csv").write_text("x\n1\n")
        make_job(id="job-123", output_dir=str(tmp_path))

        res = client.get("/jobs/job-123/outputs")
        assert res.status_code == 200
        filenames = {f["filename"] for f in res.json()["files"]}
        assert filenames == {"summary.csv", "clipA/detail.csv"}


class TestDownloadOutput:
    def test_job_not_found_returns_404(self, client):
        res = client.get("/jobs/does-not-exist/outputs/foo.csv")
        assert res.status_code == 404

    def test_no_output_dir_returns_404(self, client, make_job):
        make_job(id="job-123", output_dir=None)
        res = client.get("/jobs/job-123/outputs/foo.csv")
        assert res.status_code == 404

    def test_missing_file_returns_404(self, client, make_job, tmp_path):
        make_job(id="job-123", output_dir=str(tmp_path))
        res = client.get("/jobs/job-123/outputs/foo.csv")
        assert res.status_code == 404

    def test_serves_existing_file(self, client, make_job, tmp_path):
        (tmp_path / "foo.csv").write_text("a,b\n1,2\n")
        make_job(id="job-123", output_dir=str(tmp_path))
        res = client.get("/jobs/job-123/outputs/foo.csv")
        assert res.status_code == 200
        assert res.text == "a,b\n1,2\n"

    def test_serves_nested_file(self, client, make_job, tmp_path):
        nested = tmp_path / "clipA"
        nested.mkdir()
        (nested / "detail.csv").write_text("x\n1\n")
        make_job(id="job-123", output_dir=str(tmp_path))
        res = client.get("/jobs/job-123/outputs/clipA/detail.csv")
        assert res.status_code == 200
        assert res.text == "x\n1\n"

    def test_path_traversal_outside_output_dir_is_rejected(
        self, client, make_job, tmp_path
    ):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("top secret")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        make_job(id="job-123", output_dir=str(output_dir))

        res = client.get(f"/jobs/job-123/outputs/../{outside.name}")
        assert res.status_code in (400, 404)
        assert "top secret" not in res.text


class TestDownloadAllOutputs:
    def test_job_not_found_returns_404(self, client):
        res = client.get("/jobs/does-not-exist/outputs/download-all")
        assert res.status_code == 404

    def test_no_output_dir_returns_404(self, client, make_job):
        make_job(id="job-123", output_dir=None)
        res = client.get("/jobs/job-123/outputs/download-all")
        assert res.status_code == 404

    def test_zips_files_excluding_raw_recordings(self, client, make_job, tmp_path):
        (tmp_path / "summary.csv").write_text("a,b\n1,2\n")
        (tmp_path / "raw.aris").write_text("binary-ish")
        (tmp_path / "raw.ddf").write_text("binary-ish")
        nested = tmp_path / "clipA"
        nested.mkdir()
        (nested / "detail.csv").write_text("x\n1\n")
        make_job(id="job-123", output_dir=str(tmp_path))

        res = client.get("/jobs/job-123/outputs/download-all")
        assert res.status_code == 200
        with zipfile.ZipFile(BytesIO(res.content)) as zf:
            names = set(zf.namelist())
        assert names == {"summary.csv", "clipA/detail.csv"}


class TestStreamJobProgress:
    def test_unknown_job_closes_with_4004(self, client):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/jobs/does-not-exist/stream") as ws:
                ws.receive_text()
        assert exc_info.value.code == 4004

    def test_forwards_queued_events_then_sends_done(self, client, make_job):
        job = make_job(id="job-123", status=JobStatus.RUNNING)
        job.progress_queue.put({"event": "job_started"})

        with client.websocket_connect("/jobs/job-123/stream") as ws:
            first = json.loads(ws.receive_text())
            assert first == {"event": "job_started"}

            job.status = JobStatus.COMPLETED
            final = json.loads(ws.receive_text())
            assert final == {"event": "done", "status": "completed", "error": None}

    def test_done_event_reports_failure_error(self, client, make_job):
        job = make_job(id="job-123", status=JobStatus.RUNNING)
        job.status = JobStatus.FAILED
        job.error = "boom"

        with client.websocket_connect("/jobs/job-123/stream") as ws:
            final = json.loads(ws.receive_text())
            assert final == {"event": "done", "status": "failed", "error": "boom"}
