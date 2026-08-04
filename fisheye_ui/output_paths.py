from datetime import datetime
from pathlib import Path
from typing import List

from fisheye.common.file_system import (
    get_all_valid_files_in_dir,
    is_valid_dir,
    is_valid_file,
)
from fisheye.common.system import generate_job_id


def _candidate_files(input_path: Path) -> List[Path]:
    if is_valid_file(input_path):
        return [input_path]
    if is_valid_dir(input_path):
        return get_all_valid_files_in_dir(input_path)
    return []


def has_existing_predictions(input_path: Path, output_dir: Path) -> bool:
    """Whether any input file already has a prediction in output_dir, using the
    same "FCe_{stem}_ID_.txt" marker fisheye's own get_valid_files checks (see
    fisheye/common/file_system.py) to silently skip already-processed files."""
    return any(
        (output_dir / f"FCe_{f.stem}_ID_.txt").exists()
        for f in _candidate_files(input_path)
    )


def next_available_output_dir(base_dir: Path) -> Path:
    """A new timestamped subfolder under base_dir for a confirmed rerun, so
    it writes new results instead of overwriting existing ones or being
    silently skipped by FishEye's own already-processed check. Only used for
    confirmed reruns - a first run into an empty location still writes
    directly to the exact folder the user chose, so users find
    their output where they expect it.
    """
    return base_dir / f"{datetime.now().astimezone():%Y%m%d_%H%M%S}"
