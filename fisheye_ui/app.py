import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fisheye_ui.job_manager import _MP_CTX, _noop, job_manager
from fisheye_ui.logging import configure_logging
from fisheye_ui.routes.files import router as files_router
from fisheye_ui.routes.jobs import router as jobs_router

STATIC_DIR = Path(__file__).parent / "static"


def _warmup_forkserver() -> None:
    p = _MP_CTX.Process(target=_noop, daemon=True)
    p.start()
    p.join()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(job_manager.get_job_queue)
    if sys.platform != "win32":
        threading.Thread(target=_warmup_forkserver, daemon=True).start()
    yield


app = FastAPI(title="FishEye UI", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(files_router)
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


def main():
    host = "127.0.0.1"
    port = 8000
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
