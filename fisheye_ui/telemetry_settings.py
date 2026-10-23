import json
import os
import threading

import structlog
from pydantic import ValidationError

from fisheye_ui.enums import TelemetryChoice
from fisheye_ui.paths import TELEMETRY_SETTINGS_PATH
from fisheye_ui.schemas import TelemetrySettings

logger = structlog.get_logger()

# Guards read/write access to TELEMETRY_SETTINGS_PATH.
_lock = threading.Lock()


def enabled() -> bool:
    """Whether opt-in telemetry is available on this deployment at all.

    On by default (desktop). Turned off with FISHEYE_UI_TELEMETRY_ENABLED=0
    on the cloud GPU worker (see deploy/gpu-worker/fisheye-ui.service):
    settings here are one per machine, so on a shared server one user's
    choice - and contact details - would apply to, and be readable by,
    every other user. Per-user cloud telemetry is a separate design.
    """
    return os.environ.get("FISHEYE_UI_TELEMETRY_ENABLED", "1") != "0"


class TelemetryDisabledError(RuntimeError):
    """Raised by save() when telemetry is turned off for this deployment."""


def load() -> TelemetrySettings:
    """The saved choice, or "not chosen yet" if there's no file or it can't
    be read. Failing to "not chosen" rather than to any sending choice means
    a damaged file re-prompts the user instead of sending anything.

    Always "off" when telemetry is disabled, regardless of any file left on
    disk, so nothing downstream can treat it as a sending choice."""
    if not enabled():
        return TelemetrySettings(choice=TelemetryChoice.OFF)
    with _lock:
        try:
            with TELEMETRY_SETTINGS_PATH.open() as f:
                return TelemetrySettings.model_validate(json.load(f))
        except FileNotFoundError:
            return TelemetrySettings()
        except (OSError, json.JSONDecodeError, ValidationError):
            logger.warning("telemetry_settings_load_failed")
            return TelemetrySettings()


def save(settings: TelemetrySettings) -> None:
    """Persist the choice. Written temp-then-rename so a crash mid-write
    can't leave a half-written file behind. Raises OSError on failure -
    unlike usage counts, a consent choice that silently didn't save
    shouldn't look to the user like it did.

    Refuses to write when telemetry is disabled, so contact details can
    never be stored on a deployment that has it turned off."""
    if not enabled():
        raise TelemetryDisabledError("telemetry is disabled on this deployment")
    with _lock:
        TELEMETRY_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = TELEMETRY_SETTINGS_PATH.with_suffix(".json.tmp")
        with tmp_path.open("w") as f:
            json.dump(settings.model_dump(mode="json"), f)
        os.replace(tmp_path, TELEMETRY_SETTINGS_PATH)
