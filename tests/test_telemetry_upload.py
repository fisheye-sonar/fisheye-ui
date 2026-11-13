import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from fisheye_ui import telemetry_settings, telemetry_upload
from fisheye_ui.enums import JobStatus, TelemetryChoice
from fisheye_ui.job_manager import JobManager
from fisheye_ui.schemas import TelemetryContact, TelemetryPayload, TelemetrySettings

URL = "https://telemetry.example/"
LAMBDA_SOURCE = (
    Path(__file__).parents[1] / "deploy" / "telemetry" / "lambda_function.py"
)
NOW = datetime(2026, 11, 9, 12, 0, 0)
CONTACT = TelemetryContact(
    name="Jane Doe", institution="Caltech", email="jane@example.edu"
)


def _payload(job_id="00000000-0000-4000-8000-000000000001", **overrides):
    defaults = dict(
        job_id=job_id,
        os="darwin",
        status=JobStatus.COMPLETED,
        started_at=datetime(2026, 11, 9, 10, 0, 0),
        file_count=0,
        export_options=[],
        counts=[],
        track_stats=[],
    )
    defaults.update(overrides)
    return TelemetryPayload(**defaults)


def _choose(choice, contact=None):
    telemetry_settings.save(TelemetrySettings(choice=choice, contact=contact))


def _outbox():
    outbox = telemetry_upload.TELEMETRY_OUTBOX_DIR
    return sorted(p.name for p in outbox.glob("*.json")) if outbox.is_dir() else []


def _state():
    return json.loads(telemetry_upload.TELEMETRY_STATE_PATH.read_text())


def _write_state(state):
    path = telemetry_upload.TELEMETRY_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


class Receiver:
    """Fake telemetry receiver: records each request's reports and answers
    with `status_for(report)` per report (default "saved")."""

    def __init__(self, status_code=200, headers=None, status_for=None, on_request=None):
        self.batches = []
        self.status_code = status_code
        self.headers = headers or {}
        self.status_for = status_for or (lambda report: "saved")
        self.on_request = on_request

    def handler(self, request):
        reports = json.loads(request.content)["reports"]
        self.batches.append(reports)
        if self.on_request:
            self.on_request(len(self.batches))
        if self.status_code != 200:
            return httpx.Response(self.status_code, headers=self.headers)
        return httpx.Response(
            200, json={"results": [{"status": self.status_for(r)} for r in reports]}
        )

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
    return Receiver()


class TestEnqueue:
    @pytest.mark.parametrize("choice", [None, TelemetryChoice.OFF])
    def test_nothing_queued_unless_opted_in(self, choice):
        if choice:
            _choose(choice)
        telemetry_upload.enqueue(_payload())

        assert _outbox() == []

    def test_queued_as_job_id_when_opted_in(self):
        _choose(TelemetryChoice.ANONYMOUS)
        telemetry_upload.enqueue(_payload())

        assert _outbox() == ["00000000-0000-4000-8000-000000000001.json"]

    def test_contact_never_stored_in_outbox(self):
        """Contact details are added at upload time from the current choice,
        so an email can't sit in the outbox after switching to anonymous."""
        _choose(TelemetryChoice.CONTACT, CONTACT)
        telemetry_upload.enqueue(_payload(contact=CONTACT))

        stored = (telemetry_upload.TELEMETRY_OUTBOX_DIR / _outbox()[0]).read_text()
        assert "jane@example.edu" not in stored

    def test_outbox_capped_oldest_first(self, monkeypatch):
        monkeypatch.setattr(telemetry_upload, "MAX_OUTBOX_REPORTS", 2)
        _choose(TelemetryChoice.ANONYMOUS)
        for i in range(3):
            telemetry_upload.enqueue(
                _payload(job_id=f"00000000-0000-4000-8000-00000000000{i}")
            )
            time.sleep(0.01)  # distinct mtimes

        assert _outbox() == [
            "00000000-0000-4000-8000-000000000001.json",
            "00000000-0000-4000-8000-000000000002.json",
        ]

    def test_drops_reports_older_than_max_age(self):
        _choose(TelemetryChoice.ANONYMOUS)
        telemetry_upload.enqueue(
            _payload(job_id="00000000-0000-4000-8000-00000000000a")
        )
        old = (
            telemetry_upload.TELEMETRY_OUTBOX_DIR
            / "00000000-0000-4000-8000-00000000000a.json"
        )
        stale = time.time() - telemetry_upload.MAX_REPORT_AGE.total_seconds() - 60
        os.utime(old, (stale, stale))
        telemetry_upload.enqueue(
            _payload(job_id="00000000-0000-4000-8000-00000000000b")
        )

        assert _outbox() == ["00000000-0000-4000-8000-00000000000b.json"]


class TestIsDue:
    def test_due_when_never_uploaded(self):
        assert telemetry_upload.is_due({}, NOW) is True

    def test_not_due_within_24_hours(self):
        state = {"last_upload_at": (NOW - timedelta(hours=23)).isoformat()}
        assert telemetry_upload.is_due(state, NOW) is False

    def test_due_after_24_hours(self):
        state = {"last_upload_at": (NOW - timedelta(hours=24)).isoformat()}
        assert telemetry_upload.is_due(state, NOW) is True

    def test_future_last_upload_is_ignored(self):
        """A wrong system clock mustn't block uploads for days."""
        state = {"last_upload_at": (NOW + timedelta(days=5)).isoformat()}
        assert telemetry_upload.is_due(state, NOW) is True

    def test_not_due_while_waiting_out_retry(self):
        state = {"retry_after": (NOW + timedelta(hours=2)).isoformat()}
        assert telemetry_upload.is_due(state, NOW) is False

    def test_absurd_retry_after_is_ignored(self):
        state = {"retry_after": (NOW + timedelta(days=30)).isoformat()}
        assert telemetry_upload.is_due(state, NOW) is True

    def test_damaged_timestamps_are_treated_as_never_uploaded(self):
        state = {"last_upload_at": "not a time", "retry_after": 12}
        assert telemetry_upload.is_due(state, NOW) is True


class TestUploadIfDue:
    def _queue(self, *job_ids, choice=TelemetryChoice.ANONYMOUS, contact=None):
        _choose(choice, contact)
        for job_id in job_ids or ("00000000-0000-4000-8000-000000000001",):
            telemetry_upload.enqueue(_payload(job_id=job_id))

    def test_nothing_sent_without_url(self, receiver, monkeypatch):
        """Reports queued by a build that had a URL are never sent by one
        that doesn't."""
        self._queue()
        monkeypatch.delenv("FISHEYE_UI_TELEMETRY_URL")

        assert telemetry_upload.upload_if_due(receiver.client(), NOW) is False
        assert receiver.batches == []

    def test_nothing_sent_when_not_due(self, receiver):
        self._queue()
        _write_state({"last_upload_at": (NOW - timedelta(hours=1)).isoformat()})

        assert telemetry_upload.upload_if_due(receiver.client(), NOW) is False
        assert receiver.batches == []

    def test_nothing_sent_with_empty_outbox(self, receiver):
        _choose(TelemetryChoice.ANONYMOUS)

        assert telemetry_upload.upload_if_due(receiver.client(), NOW) is False
        assert receiver.batches == []

    def test_success_clears_outbox_and_records_time(self, receiver):
        self._queue(
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        )

        assert telemetry_upload.upload_if_due(receiver.client(), NOW) is True
        assert len(receiver.batches) == 1
        assert len(receiver.batches[0]) == 2
        assert _outbox() == []
        assert _state() == {"last_upload_at": NOW.isoformat()}

    def test_anonymous_reports_have_no_contact(self, receiver):
        self._queue()

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert "contact" not in receiver.batches[0][0]

    def test_contact_added_at_upload_time(self, receiver):
        self._queue(choice=TelemetryChoice.CONTACT, contact=CONTACT)

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert receiver.batches[0][0]["contact"]["email"] == "jane@example.edu"

    def test_switching_to_anonymous_before_upload_sends_no_contact(self, receiver):
        self._queue(choice=TelemetryChoice.CONTACT, contact=CONTACT)
        _choose(TelemetryChoice.ANONYMOUS)

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert "contact" not in receiver.batches[0][0]

    def test_opting_out_sends_nothing(self, receiver):
        self._queue()
        _choose(TelemetryChoice.OFF)

        assert telemetry_upload.upload_if_due(receiver.client(), NOW) is False
        assert receiver.batches == []

    def test_network_failure_keeps_reports_and_backs_off(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
        self._queue()

        def unreachable(request):
            raise httpx.ConnectError("offline")

        client = httpx.Client(transport=httpx.MockTransport(unreachable))
        telemetry_upload.upload_if_due(client, NOW)

        assert len(_outbox()) == 1
        state = _state()
        assert state["failures"] == 1
        retry_after = datetime.fromisoformat(state["retry_after"])
        assert NOW + timedelta(hours=1) <= retry_after <= NOW + timedelta(hours=1.1)
        assert "last_upload_at" not in state

    def test_backoff_doubles_on_repeated_failures(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
        self._queue()
        _write_state({"failures": 2})

        failing = Receiver(status_code=500)
        telemetry_upload.upload_if_due(failing.client(), NOW)

        retry_after = datetime.fromisoformat(_state()["retry_after"])
        assert NOW + timedelta(hours=4) <= retry_after <= NOW + timedelta(hours=4.4)

    def test_respects_server_retry_after(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
        self._queue()

        throttled = Receiver(status_code=429, headers={"Retry-After": "10800"})
        telemetry_upload.upload_if_due(throttled.client(), NOW)

        assert len(_outbox()) == 1
        retry_after = datetime.fromisoformat(_state()["retry_after"])
        assert retry_after >= NOW + timedelta(hours=3)

    def test_success_after_failure_resets_backoff(self, receiver):
        self._queue()
        _write_state(
            {"failures": 3, "retry_after": (NOW - timedelta(minutes=1)).isoformat()}
        )

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert _state() == {"last_upload_at": NOW.isoformat()}

    def test_per_report_results(self, monkeypatch):
        """saved and rejected leave the outbox; error stays for a retry."""
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
        self._queue(
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000003",
        )
        statuses = {
            "00000000-0000-4000-8000-000000000001": "saved",
            "00000000-0000-4000-8000-000000000002": "rejected",
            "00000000-0000-4000-8000-000000000003": "error",
        }
        mixed = Receiver(status_for=lambda report: statuses[report["job_id"]])

        telemetry_upload.upload_if_due(mixed.client(), NOW)

        assert _outbox() == ["00000000-0000-4000-8000-000000000003.json"]

    def test_oversized_single_report_is_dropped(self, monkeypatch):
        monkeypatch.setenv("FISHEYE_UI_TELEMETRY_URL", URL)
        self._queue()

        too_big = Receiver(status_code=413)
        telemetry_upload.upload_if_due(too_big.client(), NOW)

        assert _outbox() == []

    def test_batches_split_by_size(self, receiver, monkeypatch):
        self._queue(*[f"00000000-0000-4000-8000-00000000000{i}" for i in range(4)])
        one_report = len(json.dumps(_payload().model_dump(mode="json")).encode())
        monkeypatch.setattr(telemetry_upload, "MAX_BATCH_BYTES", one_report * 2 + 10)

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert [len(batch) for batch in receiver.batches] == [2, 2]
        assert _outbox() == []

    def test_batches_split_by_report_count(self, receiver, monkeypatch):
        self._queue(*[f"00000000-0000-4000-8000-00000000000{i}" for i in range(5)])
        monkeypatch.setattr(telemetry_upload, "MAX_BATCH_REPORTS", 2)

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert [len(batch) for batch in receiver.batches] == [2, 2, 1]
        assert _outbox() == []

    def test_batch_report_cap_matches_receiver(self):
        # Read from source rather than imported: the Lambda needs BUCKET_NAME
        # and AWS credentials at import time.
        match = re.search(
            r"^MAX_REPORTS_PER_BATCH = (\d+)$", LAMBDA_SOURCE.read_text(), re.M
        )
        assert telemetry_upload.MAX_BATCH_REPORTS == int(match.group(1))

    def test_opting_out_mid_upload_stops_remaining_batches(self, receiver, monkeypatch):
        self._queue(*[f"00000000-0000-4000-8000-00000000000{i}" for i in range(4)])
        one_report = len(json.dumps(_payload().model_dump(mode="json")).encode())
        monkeypatch.setattr(telemetry_upload, "MAX_BATCH_BYTES", one_report + 10)

        def opt_out_after_first(request_number):
            if request_number == 1:
                _choose(TelemetryChoice.OFF)
                telemetry_upload.clear_outbox()

        receiver.on_request = opt_out_after_first
        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert len(receiver.batches) == 1

    def test_corrupt_outbox_file_is_removed(self, receiver):
        self._queue()
        bad = (
            telemetry_upload.TELEMETRY_OUTBOX_DIR
            / "00000000-0000-4000-8000-00000000000f.json"
        )
        bad.write_text("{not json")

        telemetry_upload.upload_if_due(receiver.client(), NOW)

        assert _outbox() == []
        assert len(receiver.batches[0]) == 1


class TestOptOutClearsOutbox:
    def test_put_off_deletes_queued_reports(self, client):
        _choose(TelemetryChoice.ANONYMOUS)
        telemetry_upload.enqueue(_payload())

        client.put("/settings/telemetry", json={"choice": "off"})

        assert _outbox() == []

    def test_switching_to_contact_keeps_queued_reports(self, client):
        _choose(TelemetryChoice.ANONYMOUS)
        telemetry_upload.enqueue(_payload())

        client.put(
            "/settings/telemetry",
            json={"choice": "contact", "contact": {"email": "jane@example.edu"}},
        )

        assert len(_outbox()) == 1


class TestJobEnqueuesReport:
    def _run(self, tmp_path, monkeypatch):
        def fake_run_job(config, job_id, configure_logging=True):
            out = Path(config["output_dir"]) / f"clip_{job_id}_summary.csv"
            out.write_text("file_index,absolute_up,absolute_down,net_count\n0,3,1,2\n")

        monkeypatch.setattr("fisheye.runner.run_job", fake_run_job)
        manager = JobManager()
        return manager.create_job(
            {"input_path": str(tmp_path), "output_dir": str(tmp_path)}
        )

    def _wait_for_outbox(self, expected, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _outbox() == expected:
                return
            time.sleep(0.01)
        assert _outbox() == expected

    def test_finished_job_is_queued_when_opted_in(self, tmp_path, monkeypatch):
        _choose(TelemetryChoice.ANONYMOUS)
        job_id = self._run(tmp_path, monkeypatch)

        self._wait_for_outbox([f"{job_id}.json"])
        report = json.loads(
            (telemetry_upload.TELEMETRY_OUTBOX_DIR / f"{job_id}.json").read_text()
        )
        assert report["status"] == "completed"
        assert report["counts"] == [
            {"file_index": 0, "absolute_up": 3, "absolute_down": 1, "net_count": 2}
        ]

    def test_finished_job_not_queued_when_not_chosen(self, tmp_path, monkeypatch):
        job_id = self._run(tmp_path, monkeypatch)
        time.sleep(0.2)

        assert f"{job_id}.json" not in _outbox()
