import threading
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from fisheye_ui.job_manager import job_manager
from fisheye_ui.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(job_manager.get_job_queue)
    yield


app = FastAPI(title="FishEye UI", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>FishEye UI</h1><p>Server is running.</p>"


def main():
    host = "127.0.0.1"
    port = 8000
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
