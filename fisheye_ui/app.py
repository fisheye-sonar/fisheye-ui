import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fisheye_ui.job_manager import job_manager
from fisheye_ui.logging import configure_logging
from fisheye_ui.routes.files import router as files_router
from fisheye_ui.routes.jobs import router as jobs_router
from fisheye_ui.routes.platform import router as platform_router

STATIC_DIR = Path(__file__).parent / "static"


def _preimport() -> None:
    """Pre-import fisheye/torch in a background thread so the first job starts fast."""
    from fisheye.common.logging import progress_queue  # noqa
    from fisheye.runner import run_job  # noqa


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(job_manager.get_job_queue)
    threading.Thread(target=_preimport, daemon=True).start()
    yield


app = FastAPI(title="FishEye UI", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(files_router)
app.include_router(platform_router)
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg")


@app.get("/health")
async def health():
    return {"status": "ok"}


def main():
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", 8000))
    # Set by the Electron shell, which opens its own window instead
    # the system browser is only wanted for `poetry run fisheye-ui` dev use.
    if not os.environ.get("FISHEYE_UI_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
