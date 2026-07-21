import os
import tempfile
from pathlib import Path

# Shared by routes/files.py (writes uploads here) and job_manager.py (deletes
# a job's input file from here once it's done with it) - a plain module
# avoids a circular import between the two.
#
# Defaults to the system temp dir, but deployments where that's backed by
# tmpfs (e.g. the GPU worker, whose /tmp is wiped whenever the idle-watcher
# stops the instance) should override FISHEYE_UI_UPLOAD_DIR to point at
# persistent disk instead, so uploaded input and not-yet-downloaded results
# survive a stop/start cycle.
UPLOAD_DIR = Path(
    os.environ.get("FISHEYE_UI_UPLOAD_DIR")
    or Path(tempfile.gettempdir()) / "fisheye-ui-uploads"
)
