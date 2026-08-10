import json
import os
import threading

import structlog

from fisheye_ui.paths import USAGE_PATH

logger = structlog.get_logger()

# How many jobs a given username may create in the cloud deployment, counted
# across all sessions (not reset per-login). Only enforced for requests that
# carry a username (see USER_HEADER in routes/jobs.py) - Caddy's basic_auth
# is what sets that header on the cloud deployment, so desktop/local use
# (no Caddy in front) is never limited.
MAX_JOBS_PER_USER = int(os.environ.get("FISHEYE_UI_MAX_JOBS_PER_USER", "10"))

# The one existing shared account, grandfathered in with unlimited runs - set
# to whatever username the existing Caddy basic_auth credential uses.
UNLIMITED_USER = os.environ.get("FISHEYE_UI_UNLIMITED_USER", "")

# Guards read-modify-write access to USAGE_PATH.
_lock = threading.Lock()


def is_limited(username: str) -> bool:
    return bool(username) and username != UNLIMITED_USER


def _load() -> dict:
    try:
        with USAGE_PATH.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save(counts: dict) -> None:
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = USAGE_PATH.with_suffix(".json.tmp")
        with tmp_path.open("w") as f:
            json.dump(counts, f)
        os.replace(tmp_path, USAGE_PATH)
    except OSError:
        logger.warning("usage_persist_failed")


def jobs_used(username: str) -> int:
    with _lock:
        return _load().get(username, 0)


def record_job(username: str) -> None:
    with _lock:
        counts = _load()
        counts[username] = counts.get(username, 0) + 1
        _save(counts)
