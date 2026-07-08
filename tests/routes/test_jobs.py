from fisheye_ui.enums import JobStatus


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
