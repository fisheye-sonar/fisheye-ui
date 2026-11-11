"""Opt-in telemetry outbox and daily upload.

Flow: each finished job's report is written to TELEMETRY_OUTBOX_DIR as
<job_id>.json (enqueue). A background thread checks at startup and then
hourly (start_uploader), and if the user is opted in and the last successful
upload was 24+ hours ago, sends everything in the outbox to
FISHEYE_UI_TELEMETRY_URL in batches (upload_if_due). A report is deleted
from the outbox only once the server confirms it was saved, so whatever is
still in the outbox is exactly what hasn't been uploaded. The server keys
reports by job_id, so re-sending one whose confirmation got lost overwrites
it rather than duplicating it.

Consent is always checked against the user's *current* choice at upload
time: opting out clears the outbox (clear_outbox), and contact details are
only added to reports as they're sent, never stored in the outbox.
"""

import json
import os
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
import structlog

from fisheye_ui import telemetry_settings
from fisheye_ui.enums import TelemetryChoice
from fisheye_ui.paths import TELEMETRY_OUTBOX_DIR, TELEMETRY_STATE_PATH
from fisheye_ui.schemas import TelemetryPayload

logger = structlog.get_logger()

UPLOAD_INTERVAL = timedelta(hours=24)
CHECK_INTERVAL_SECONDS = 60 * 60

# After a failed upload, wait 1h, 2h, 4h, ... (capped at the daily interval)
# before trying again, plus up to 10% random jitter so many installs that
# failed together (e.g. the receiver was down) don't all retry in lockstep.
RETRY_BASE = timedelta(hours=1)

# Keeps a long-offline install from building up an unbounded outbox. Oldest
# reports are dropped first.
MAX_OUTBOX_REPORTS = 500
MAX_REPORT_AGE = timedelta(days=90)

# Batches are kept under the receiver's 1 MB request limit (see
# deploy/telemetry/lambda_function.py). A single report bigger than this is
# dropped rather than retried forever.
MAX_BATCH_BYTES = 900 * 1024

REQUEST_TIMEOUT_SECONDS = 30

# Ensures the startup check and the hourly check never upload at the same time.
_upload_lock = threading.Lock()
# Guards writes to the outbox dir and state file.
_files_lock = threading.Lock()


def telemetry_url() -> Optional[str]:
    """Where reports are sent. Set by the Electron app for real installs;
    unset when running from the repo, in which case nothing is ever sent
    (reports still collect in the outbox, which is handy for inspecting
    them)."""
    return os.environ.get("FISHEYE_UI_TELEMETRY_URL") or None


def _opted_in(settings) -> bool:
    return settings.choice in (TelemetryChoice.ANONYMOUS, TelemetryChoice.CONTACT)


def _write_json_atomic(path, data) -> None:
    """Temp-then-rename so a crash mid-write can never leave a half-written
    file behind - same approach as JobManager._persist and usage._save."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)


def enqueue(payload: TelemetryPayload) -> None:
    """Add a finished job's report to the outbox if the user is opted in.
    Called from JobManager._run; never raises, since telemetry must never
    affect a job."""
    try:
        if not _opted_in(telemetry_settings.load()):
            return
        data = payload.model_dump(mode="json", exclude={"contact"})
        with _files_lock:
            _write_json_atomic(TELEMETRY_OUTBOX_DIR / f"{payload.job_id}.json", data)
            _prune_outbox()
    except Exception:
        logger.warning("telemetry_enqueue_failed")


def clear_outbox() -> None:
    """Delete every queued report - called when the user opts out, so
    reports queued while they were opted in are never sent."""
    with _files_lock:
        for path in _outbox_files():
            path.unlink(missing_ok=True)


def _outbox_files() -> List:
    if not TELEMETRY_OUTBOX_DIR.is_dir():
        return []
    return sorted(TELEMETRY_OUTBOX_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)


def _prune_outbox() -> None:
    """Drop reports older than MAX_REPORT_AGE, then the oldest beyond
    MAX_OUTBOX_REPORTS. Caller holds _files_lock."""
    cutoff = time.time() - MAX_REPORT_AGE.total_seconds()
    files = _outbox_files()
    for path in files:
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
    files = _outbox_files()
    for path in files[: max(0, len(files) - MAX_OUTBOX_REPORTS)]:
        path.unlink(missing_ok=True)


def _load_state() -> Dict:
    try:
        with TELEMETRY_STATE_PATH.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Missing or damaged: treated as "never uploaded", so the worst case
        # is one upload earlier than it would otherwise have been.
        return {}


def _parse_time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def is_due(state: Dict, now: datetime) -> bool:
    """Whether an upload should happen now, given the saved state.

    Not due while waiting out a retry delay after a failure, or within
    UPLOAD_INTERVAL of the last successful upload. A saved time in the
    future (e.g. the system clock was wrong when it was written) is ignored
    rather than allowed to block uploads for days.
    """
    retry_after = _parse_time(state.get("retry_after"))
    if retry_after and now < retry_after <= now + UPLOAD_INTERVAL:
        return False
    last_upload_at = _parse_time(state.get("last_upload_at"))
    if last_upload_at and last_upload_at <= now < last_upload_at + UPLOAD_INTERVAL:
        return False
    return True


def _retry_delay(failures: int, server_retry_after: Optional[float]) -> timedelta:
    delay = min(RETRY_BASE * (2 ** max(0, failures - 1)), UPLOAD_INTERVAL)
    if server_retry_after:
        delay = max(delay, timedelta(seconds=server_retry_after))
    return delay * (1 + random.uniform(0, 0.1))


def _batches(reports: List[Tuple]) -> List[List[Tuple]]:
    """Group (path, report) pairs into batches whose JSON stays under
    MAX_BATCH_BYTES. Reports too big to fit even alone get their own
    single-report batch, which the server will reject (413) and which is
    then dropped."""
    batches, current, current_size = [], [], 0
    for path, report in reports:
        size = len(json.dumps(report).encode("utf-8"))
        if current and current_size + size > MAX_BATCH_BYTES:
            batches.append(current)
            current, current_size = [], 0
        current.append((path, report))
        current_size += size
    if current:
        batches.append(current)
    return batches


def _server_retry_after(response: httpx.Response) -> Optional[float]:
    try:
        return float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def _send_batch(
    client: httpx.Client, url: str, batch: List[Tuple]
) -> Tuple[bool, Optional[float]]:
    """Send one batch and delete the reports the server confirmed (or
    permanently rejected) from the outbox.

    Returns (succeeded, server_retry_after). A batch counts as succeeded if
    the server answered it - reports it couldn't store (status "error")
    stay in the outbox for the next upload either way.
    """
    try:
        response = client.post(url, json={"reports": [report for _, report in batch]})
    except httpx.HTTPError:
        return False, None

    if response.status_code == 413 and len(batch) == 1:
        # Too big to ever be accepted - drop it instead of retrying forever.
        batch[0][0].unlink(missing_ok=True)
        logger.warning("telemetry_report_dropped", reason="too_large")
        return True, None
    if response.status_code != 200:
        return False, _server_retry_after(response)

    try:
        results = response.json()["results"]
    except (ValueError, KeyError, TypeError):
        return False, None

    # Results come back in the same order as the reports were sent, so
    # they're matched by position rather than by job_id.
    for (path, _), result in zip(batch, results):
        status = result.get("status") if isinstance(result, dict) else None
        if status == "saved":
            path.unlink(missing_ok=True)
        elif status == "rejected":
            # Malformed in a way retrying won't fix.
            path.unlink(missing_ok=True)
            logger.warning("telemetry_report_dropped", reason="rejected")
    return True, None


def upload_if_due(
    client: Optional[httpx.Client] = None, now: Optional[datetime] = None
) -> bool:
    """Upload everything in the outbox if the user is opted in and an upload
    is due. Returns whether an upload was attempted. Never raises."""
    if not _upload_lock.acquire(blocking=False):
        return False  # another check is already uploading
    try:
        now = now or datetime.utcnow()
        url = telemetry_url()
        settings = telemetry_settings.load()
        if not url or not _opted_in(settings):
            return False

        with _files_lock:
            _prune_outbox()
            files = _outbox_files()
            state = _load_state()
        if not files or not is_due(state, now):
            return False

        contact = (
            settings.contact.model_dump(mode="json")
            if settings.choice == TelemetryChoice.CONTACT and settings.contact
            else None
        )
        reports = []
        for path in files:
            try:
                report = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                continue
            report.pop("contact", None)
            if contact:
                report["contact"] = contact
            reports.append((path, report))

        own_client = client is None
        client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        )
        succeeded, server_retry_after = True, None
        try:
            for batch in _batches(reports):
                # Re-checked per batch so opting out mid-upload stops it -
                # clear_outbox has already deleted the files, but these
                # reports were read before that.
                if not _opted_in(telemetry_settings.load()):
                    return True
                succeeded, server_retry_after = _send_batch(client, url, batch)
                if not succeeded:
                    break
        finally:
            if own_client:
                client.close()

        with _files_lock:
            if succeeded:
                state = {"last_upload_at": now.isoformat()}
            else:
                failures = state.get("failures", 0) + 1
                state = {
                    **state,
                    "failures": failures,
                    "retry_after": (
                        now + _retry_delay(failures, server_retry_after)
                    ).isoformat(),
                }
            _write_json_atomic(TELEMETRY_STATE_PATH, state)

        # Counts only - never report contents or contact details.
        logger.info(
            "telemetry_upload",
            succeeded=succeeded,
            pending=len(_outbox_files()),
        )
        return True
    except Exception:
        logger.warning("telemetry_upload_failed")
        return False
    finally:
        _upload_lock.release()


def _upload_loop() -> None:
    while True:
        upload_if_due()
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_uploader() -> None:
    """Start the background thread that checks at startup and then hourly
    whether a telemetry upload is due. Called once from app startup."""
    if not telemetry_settings.enabled():
        return
    threading.Thread(target=_upload_loop, daemon=True).start()
