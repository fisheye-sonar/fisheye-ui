"""Fail if pyproject.toml, electron/package.json, and fisheye_ui/__init__.py
disagree on the app version.

These three are hand-edited independently (Poetry, electron-builder, and the
PyInstaller-frozen backend each need their own copy - see fisheye_ui/__init__.py
for why), so nothing else catches them drifting apart.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find a version in pyproject.toml")
    return match.group(1)


def _electron_version() -> str:
    data = json.loads((REPO_ROOT / "electron" / "package.json").read_text())
    return data["version"]


def _fisheye_ui_version() -> str:
    text = (REPO_ROOT / "fisheye_ui" / "__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find __version__ in fisheye_ui/__init__.py")
    return match.group(1)


def main() -> int:
    versions = {
        "pyproject.toml": _pyproject_version(),
        "electron/package.json": _electron_version(),
        "fisheye_ui/__init__.py": _fisheye_ui_version(),
    }
    if len(set(versions.values())) > 1:
        print("Version mismatch across files:")
        for path, version in versions.items():
            print(f"  {path}: {version}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())