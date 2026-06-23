import queue
from typing import Any, Callable, Dict, Optional

import structlog
from fisheye.common.logging import setup_logging as _fisheye_setup_logging


def configure_logging(get_job_queue: Callable[[str], Optional[queue.Queue]]) -> None:
    """Configure structlog at server startup with per-job progress routing.

    Extends FishEye's logging setup with two additions:
    - merge_contextvars: pulls job_id bound in each job thread into every log event
    - progress router: copies events onto the job's queue for WebSocket streaming
    """
    _fisheye_setup_logging(file_logging=False)

    processors = list(structlog.get_config()["processors"])

    if structlog.contextvars.merge_contextvars not in processors:
        processors.insert(0, structlog.contextvars.merge_contextvars)

    # insert router before the final wrap_for_formatter
    processors.insert(-1, _make_progress_router(get_job_queue))

    structlog.configure(processors=processors)


def _make_progress_router(get_job_queue: Callable[[str], Optional[queue.Queue]]):
    """Create a structlog event processor that routes progress events to the job's queue."""

    def _route(logger, method: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        job_id = event_dict.get("job_id")
        if job_id:
            q = get_job_queue(job_id)
            if q is not None:
                try:
                    q.put_nowait(dict(event_dict))
                except queue.Full:
                    pass
        return event_dict

    return _route
