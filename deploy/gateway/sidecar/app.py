import json
import logging
import os
import threading
import time
from enum import Enum
from pathlib import Path

import boto3
import httpx
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
CADDY_ACCESS_LOG = Path(os.environ.get("CADDY_ACCESS_LOG", "/var/log/caddy/access.log"))


class State(str, Enum):
    ASLEEP = "asleep"
    STARTING = "starting"
    READY = "ready"


ec2 = boto3.client("ec2", region_name=AWS_REGION)
app = FastAPI(title="FishEye UI gateway sidecar")

_lock = threading.Lock()
_state = State.ASLEEP


def _current_instance_state() -> str:
    resp = ec2.describe_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"]


def _sync_state_from_aws() -> None:
    """Reconcile in-memory state with the real instance state at startup,
    in case the sidecar restarts while the worker happens to be running."""
    global _state
    aws_state = _current_instance_state()
    with _lock:
        _state = State.READY if aws_state == "running" else State.ASLEEP
    logger.info("synced state from AWS (%s) -> %s", aws_state, _state.value)


def _wake_worker() -> None:
    global _state
    logger.info("waking GPU worker %s", GPU_WORKER_INSTANCE_ID)
    ec2.start_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])

    health_url = f"http://{GPU_WORKER_PRIVATE_IP}:{GPU_WORKER_PORT}/health"
    deadline = time.time() + WAKE_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            resp = httpx.get(health_url, timeout=2)
            if resp.status_code == 200:
                with _lock:
                    _state = State.READY
                logger.info("GPU worker is ready")
                return
        except httpx.HTTPError:
            pass
        time.sleep(HEALTH_POLL_INTERVAL_SECONDS)

    logger.error(
        "GPU worker did not become healthy within %ss, reverting to asleep",
        WAKE_TIMEOUT_SECONDS,
    )
    with _lock:
        _state = State.ASLEEP


def _last_request_time() -> float | None:
    """Timestamp of the most recent entry in Caddy's JSON access log, or
    None if the log doesn't exist yet or has no entries. Used as the
    activity signal for the idle-watcher instead of tracking requests
    separately, since Caddy already logs every proxied request."""
    if not CADDY_ACCESS_LOG.exists():
        return None
    try:
        with CADDY_ACCESS_LOG.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = 4096
            data = b""
            while size > 0 and b"\n" not in data.strip():
                step = min(chunk, size)
                size -= step
                f.seek(size)
                data = f.read() + data
        last_line = data.strip().split(b"\n")[-1]
        entry = json.loads(last_line)
        return entry.get("ts")
    except (OSError, ValueError, IndexError):
        return None


def _idle_watcher_loop() -> None:
    global _state
    while True:
        time.sleep(IDLE_CHECK_INTERVAL_SECONDS)
        with _lock:
            state = _state
        if state != State.READY:
            continue

        last_active = _last_request_time()
        if last_active is None:
            continue
        idle_for = time.time() - last_active
        if idle_for < IDLE_TIMEOUT_SECONDS:
            continue

        logger.info("idle for %.0fs, stopping GPU worker", idle_for)
        ec2.stop_instances(InstanceIds=[GPU_WORKER_INSTANCE_ID])
        with _lock:
            _state = State.ASLEEP


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
