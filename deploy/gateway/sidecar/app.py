import logging
import os
import threading
import time
from enum import Enum

import boto3
import httpx
from botocore.exceptions import ClientError
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway-sidecar")

GPU_WORKER_INSTANCE_ID = os.environ["GPU_WORKER_INSTANCE_ID"]
GPU_WORKER_PRIVATE_IP = os.environ["GPU_WORKER_PRIVATE_IP"]
GPU_WORKER_PORT = int(os.environ.get("GPU_WORKER_PORT", 8000))
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", 900))
IDLE_CHECK_INTERVAL_SECONDS = int(os.environ.get("IDLE_CHECK_INTERVAL_SECONDS", 60))
HEALTH_POLL_INTERVAL_SECONDS = float(os.environ.get("HEALTH_POLL_INTERVAL_SECONDS", 3))
WAKE_TIMEOUT_SECONDS = int(os.environ.get("WAKE_TIMEOUT_SECONDS", 180))
STOP_TIMEOUT_SECONDS = int(os.environ.get("STOP_TIMEOUT_SECONDS", 120))


class State(str, Enum):
    ASLEEP = "asleep"
    STARTING = "starting"
    READY = "ready"


ec2 = boto3.client("ec2", region_name=AWS_REGION)
app = FastAPI(title="FishEye UI gateway sidecar")

_lock = threading.Lock()
_state = State.ASLEEP
# When the worker last became READY - the idle-watcher's fallback clock for
# "no job has ever run yet on this wake cycle" (see _idle_watcher_loop).
_ready_since: float | None = None


def _current_instance_state() -> str:
    resp = ec2.describe_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"]


def _sync_state_from_aws() -> None:
    """Reconcile in-memory state with the real instance state at startup,
    in case the sidecar restarts while the worker happens to be running."""
    global _state, _ready_since
    aws_state = _current_instance_state()
    new_state = State.READY if aws_state == "running" else State.ASLEEP
    with _lock:
        # Only reset the idle clock on an actual asleep/starting -> ready
        # transition, not on every resync of an already-ready worker (that
        # would mean it could never go idle, since /gateway-status polls
        # trigger a resync on almost every call).
        if new_state == State.READY and _state != State.READY:
            _ready_since = time.time()
        _state = new_state
    logger.info("synced state from AWS (%s) -> %s", aws_state, _state.value)


def _start_instance_with_retry(deadline: float) -> bool:
    """Call start_instances, retrying while AWS reports the instance is
    still IncorrectInstanceState - this happens if a wake is triggered
    right after the idle-watcher's stop_instances call, before AWS has
    actually finished transitioning the instance out of "stopping"."""
    while time.time() < deadline:
        try:
            ec2.start_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "IncorrectInstanceState":
                raise
            logger.info("instance not startable yet (still stopping), retrying")
            time.sleep(HEALTH_POLL_INTERVAL_SECONDS)
    return False


def _wake_worker() -> None:
    global _state, _ready_since
    logger.info("waking GPU worker %s", GPU_WORKER_INSTANCE_ID)
    deadline = time.time() + WAKE_TIMEOUT_SECONDS

    try:
        if not _start_instance_with_retry(deadline):
            logger.error("GPU worker never left 'stopping' before the deadline")
            return

        health_url = f"http://{GPU_WORKER_PRIVATE_IP}:{GPU_WORKER_PORT}/health"
        while time.time() < deadline:
            try:
                resp = httpx.get(health_url, timeout=2)
                if resp.status_code == 200:
                    with _lock:
                        _state = State.READY
                        _ready_since = time.time()
                    logger.info("GPU worker is ready")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(HEALTH_POLL_INTERVAL_SECONDS)

        logger.error(
            "GPU worker did not become healthy within %ss, reverting to asleep",
            WAKE_TIMEOUT_SECONDS,
        )
    except Exception:
        # Any unexpected failure here (e.g. IAM/permissions) must not leave
        # _state wedged at STARTING forever - the finally block below always
        # reverts to ASLEEP unless we actually reached READY.
        logger.exception("wake attempt failed unexpectedly")
    finally:
        with _lock:
            if _state != State.READY:
                _state = State.ASLEEP


def _get_job_status() -> dict | None:
    """Ask the GPU worker for its job activity: whether a job is pending/
    running, and how long it's been since the last one finished. Returns
    None if the worker couldn't be reached (treated as "don't know" by the
    caller, not as "no active jobs") so a transient network blip can't
    cause the idle-watcher to stop a worker that's actually mid job."""
    url = f"http://{GPU_WORKER_PRIVATE_IP}:{GPU_WORKER_PORT}/jobs/active"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return {"active": data["active"], "idle_seconds": data.get("idle_seconds")}
    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning("could not reach %s to check job status", url)
        return None


def _stop_worker() -> None:
    """Stop the instance and wait for AWS to confirm it actually reached
    'stopped' before marking state ASLEEP - otherwise a wake triggered
    right after this can hit IncorrectInstanceState because the instance
    is still mid-'stopping' (this is exactly what happened during testing:
    a wake landed while the previous stop hadn't finished yet)."""
    global _state
    ec2.stop_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])

    deadline = time.time() + STOP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if _current_instance_state() == "stopped":
            break
        time.sleep(HEALTH_POLL_INTERVAL_SECONDS)
    else:
        logger.warning(
            "GPU worker did not report 'stopped' within %ss, marking asleep anyway",
            STOP_TIMEOUT_SECONDS,
        )

    with _lock:
        _state = State.ASLEEP
    logger.info("GPU worker is now stopped")


def _idle_watcher_loop() -> None:
    while True:
        time.sleep(IDLE_CHECK_INTERVAL_SECONDS)
        with _lock:
            state = _state
            ready_since = _ready_since
        if state != State.READY:
            continue

        job_status = _get_job_status()
        if job_status is None:
            continue  # can't tell - don't risk stopping a worker mid-job

        if job_status["active"]:
            continue  # a job is pending/running - never stop

        # No job running. Idle time is measured from the most recent job
        # finishing, not from HTTP traffic - composing the form or reading
        # a completed job's results isn't "activity" for auto-sleep. If no
        # job has ever run this wake cycle, fall back to time since wake.
        idle_seconds = job_status["idle_seconds"]
        if idle_seconds is None:
            idle_seconds = time.time() - ready_since if ready_since else 0

        if idle_seconds < IDLE_TIMEOUT_SECONDS:
            continue

        logger.info(
            "idle for %.0fs with no active job, stopping GPU worker", idle_seconds
        )
        _stop_worker()


@app.on_event("startup")
def on_startup() -> None:
    _sync_state_from_aws()
    threading.Thread(target=_idle_watcher_loop, daemon=True).start()


def _resync_unless_starting() -> None:
    """Re-check the real AWS state before trusting the cached in-memory
    state, unless a wake is actively in progress. _state only gets updated
    by this sidecar's own actions (its wake logic, its idle-watcher) - if
    the instance is stopped/started by anything else (manually, another
    tool), the cached state would otherwise go stale and never notice."""
    with _lock:
        current = _state
    if current != State.STARTING:
        _sync_state_from_aws()


@app.get("/gateway-status")
def gateway_status():
    _resync_unless_starting()
    with _lock:
        return {"state": _state.value}


@app.post("/gateway-wake")
def gateway_wake():
    global _state
    _resync_unless_starting()

    should_start = False
    with _lock:
        if _state == State.ASLEEP:
            _state = State.STARTING
            should_start = True
        current = _state
    if should_start:
        threading.Thread(target=_wake_worker, daemon=True).start()
    return {"state": current.value}
