import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from enum import Enum
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import ClientError
from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

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

# Self-serve access: a Google Form + Apps Script (see deploy/gateway/README.md)
# emails a code to whoever requests access and pushes {email, code} to
# POST /allowlist here. GET /verify is what Caddy's forward_auth calls on
# every request - it must never need to touch ALLOWLIST_PATH itself (that's
# only read at /login time), so a signed session cookie is what actually
# gates ongoing access.
ALLOWLIST_PATH = Path(
    os.environ.get("ALLOWLIST_PATH", "/opt/fisheye-gateway-sidecar/allowlist.json")
)
# Shared secret the Apps Script sends when calling POST /allowlist - without
# this, anyone who could reach the sidecar could add themselves.
GATEWAY_ADMIN_SECRET = os.environ.get("GATEWAY_ADMIN_SECRET", "")
# Signs the session cookie issued by POST /login. Session validity is proven
# by this signature alone (stateless), not by re-checking the allowlist file.
GATEWAY_SESSION_SECRET = os.environ.get("GATEWAY_SESSION_SECRET", "")
SESSION_TTL_SECONDS = int(
    os.environ.get("GATEWAY_SESSION_TTL_SECONDS", 60 * 60 * 24 * 30)
)
SESSION_COOKIE_NAME = "fisheye_session"


class State(str, Enum):
    ASLEEP = "asleep"
    STARTING = "starting"
    READY = "ready"


ec2 = boto3.client("ec2", region_name=AWS_REGION)
app = FastAPI(title="FishEye UI gateway sidecar")

# Guards read-modify-write access to ALLOWLIST_PATH - separate from _lock
# below, which guards the unrelated wake/sleep state machine.
_allowlist_lock = threading.Lock()
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

        # No job is running. Measure idle time from the most recent job
        # # finishing, not from HTTP traffic. Viewing completed results or
        # # filling out the submission form shouldn't reset the auto-sleep
        # # timer. If no job has finished during this wake cycle, fall back
        # # to the time since the worker became ready.
        idle_seconds = job_status["idle_seconds"]
        time_since_ready = time.time() - ready_since if ready_since else 0

        # idle_seconds is persisted across restarts. If the last job finished
        # before this wake cycle (e.., just before the idle watcher
        # stopped the worker), the restored value could make the worker appear
        # idle immediately after starting, before any new jobs can be submitted.
        # Cap the idle time to the duration of the current wake cycle.
        if idle_seconds is None or idle_seconds > time_since_ready:
            idle_seconds = time_since_ready

        if idle_seconds < IDLE_TIMEOUT_SECONDS:
            continue

        logger.info(
            "idle for %.0fs with no active job, stopping GPU worker", idle_seconds
        )
        _stop_worker()


class AllowlistEntry(BaseModel):
    email: str
    code: str


class LoginRequest(BaseModel):
    email: str
    code: str


def _load_allowlist() -> dict:
    try:
        with ALLOWLIST_PATH.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_allowlist(entries: dict) -> None:
    ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ALLOWLIST_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(entries, f)
    os.replace(tmp_path, ALLOWLIST_PATH)


def _sign_session(email: str, expires_at: int) -> str:
    """Session token = base64url(email|expiry) + '.' + HMAC of that string.
    Self-contained on purpose - /verify runs on every request and must not
    need to touch ALLOWLIST_PATH to check it."""
    encoded = (
        base64.urlsafe_b64encode(f"{email}|{expires_at}".encode()).decode().rstrip("=")
    )
    sig = hmac.new(
        GATEWAY_SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{sig}"


def _verify_session(token: str) -> str | None:
    """Returns the email the token was issued for, or None if the token is
    missing, malformed, tampered with, or expired."""
    try:
        encoded, sig = token.split(".", 1)
    except ValueError:
        return None

    expected_sig = hmac.new(
        GATEWAY_SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        email, expires_at = payload.rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None

    if time.time() > int(expires_at):
        return None
    return email


@app.on_event("startup")
def on_startup() -> None:
    if not GATEWAY_ADMIN_SECRET or not GATEWAY_SESSION_SECRET:
        logger.warning(
            "GATEWAY_ADMIN_SECRET and/or GATEWAY_SESSION_SECRET are unset - "
            "/allowlist and /login are not safe to expose until both are set"
        )
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


@app.post("/allowlist")
def add_to_allowlist(entry: AllowlistEntry, x_admin_secret: str = Header(default="")):
    """Called by the Apps Script bound to the access-request Google Form
    (see README) - not internet-facing, same as every other route here.
    Upserts on purpose: re-submitting the form is how someone gets a fresh
    code if they lose the one they were emailed."""
    if not GATEWAY_ADMIN_SECRET or not hmac.compare_digest(
        x_admin_secret, GATEWAY_ADMIN_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    email = entry.email.strip().lower()
    with _allowlist_lock:
        entries = _load_allowlist()
        entries[email] = {"code": entry.code, "added_at": time.time()}
        _save_allowlist(entries)
    return {"ok": True}


@app.post("/login")
def login(payload: LoginRequest, response: Response):
    email = payload.email.strip().lower()
    with _allowlist_lock:
        record = _load_allowlist().get(email)

    if not record or not hmac.compare_digest(
        record.get("code", ""), payload.code.strip()
    ):
        raise HTTPException(status_code=401, detail="Invalid email or code")

    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    response.set_cookie(
        SESSION_COOKIE_NAME,
        _sign_session(email, expires_at),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"ok": True}


@app.get("/verify")
def verify(request: Request, response: Response):
    """What Caddy's forward_auth calls on every request. A 200 here (with
    X-Fisheye-User set) lets the request through to the GPU worker via
    forward_auth's copy_headers; a 401 sends the browser to /login instead -
    see the Caddyfile example in README.md."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    email = _verify_session(token) if token else None
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")

    response.headers["X-Fisheye-User"] = email
    return {"ok": True}
