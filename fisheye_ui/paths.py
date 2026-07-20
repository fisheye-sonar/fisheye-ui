import tempfile
from pathlib import Path

# Shared by routes/files.py (writes uploads here) and job_manager.py (deletes
# a job's input file from here once it's done with it) - a plain module
# avoids a circular import between the two.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "fisheye-ui-uploads"
