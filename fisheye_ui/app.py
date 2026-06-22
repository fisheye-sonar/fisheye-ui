import threading
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="FishEye UI")


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