from fastapi import APIRouter, HTTPException

from fisheye_ui import telemetry_settings
from fisheye_ui.schemas import TelemetrySettings, TelemetrySettingsRequest

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/telemetry", response_model=TelemetrySettings)
async def get_telemetry_settings():
    """The user's opt-in telemetry choice. choice is null until they've
    made one - the frontend's cue to show the opt-in dialog - and nothing
    is sent until then."""
    return telemetry_settings.load()


@router.put("/telemetry", response_model=TelemetrySettings)
async def put_telemetry_settings(request: TelemetrySettingsRequest):
    """Replace the user's opt-in telemetry choice and return what was saved.

    Contact details are dropped unless choice is "contact" (see
    TelemetrySettings), so the response can differ from the request.
    """
    settings = TelemetrySettings.model_validate(request.model_dump())
    try:
        telemetry_settings.save(settings)
    except telemetry_settings.TelemetryDisabledError:
        raise HTTPException(
            status_code=403, detail="Usage reporting is turned off on this server"
        )
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Couldn't save your usage reporting choice. Please try again.",
        )
    return settings
