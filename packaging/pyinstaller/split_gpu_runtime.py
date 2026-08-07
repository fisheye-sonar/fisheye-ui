"""Split the Windows PyInstaller build into a small base install and a
separate downloadable GPU (CUDA/cuDNN) runtime archive.

electron-builder's bundled NSIS compiler (makensis) has a hard ~2GB payload
limit, and the CUDA-enabled torch build alone is ~4.4GB. Run this after the
PyInstaller build and before `electron-builder --win` — it moves the
CUDA-specific libraries out of dist/fisheye-ui-backend into a separate zip
that main.js's gpuSetup.js downloads (or loads from a local file) on first
launch, well after NSIS has already built a small installer.

Which files are "CUDA-specific" isn't just a filename question: on Windows,
torch.dll and torch_python.dll (the actual Python binding libraries) have a
*hard* PE import-table dependency on torch_cuda.dll — not a lazy one
resolved only when .cuda() is called. torch's own _load_dll_libraries()
(torch/__init__.py) also eagerly LoadLibrary's every *.dll physically
present in torch/lib at `import torch` time, so any file left behind whose
dependencies are missing breaks the import outright, not just GPU features.
So rather than guess by name, this walks the real import table of every
file (via pefile, already a transitive PyInstaller dependency) starting
from the obviously-CUDA-named files and expanding to a full closure - any
kept file that imports a moved file has to move too, repeated to a fixed
point. That makes the split correct by construction and lets it survive
torch version bumps that might change this dependency graph.
"""
import fnmatch
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pefile

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "packaging" / "pyinstaller" / "dist" / "fisheye-ui-backend"
TORCH_LIB_DIR = DIST_DIR / "_internal" / "torch" / "lib"
GPU_RUNTIME_STAGE_DIR = REPO_ROOT / "packaging" / "pyinstaller" / "dist" / "gpu-runtime"
GPU_RUNTIME_ZIP = REPO_ROOT / "packaging" / "pyinstaller" / "dist" / "fisheye-ui-gpu-runtime-win.zip"
MANIFEST_PATH = REPO_ROOT / "electron" / "resources" / "gpu-runtime.manifest.json"
ELECTRON_PACKAGE_JSON = REPO_ROOT / "electron" / "package.json"

# Seed set: obviously CUDA-toolkit-named libraries. The dependency closure
# below expands this to anything else that turns out to require one of
# them (e.g. torch_python.dll, torch.dll, shm.dll, caffe2_nvrtc.dll).
SEED_CUDA_DLL_GLOBS = ("cu*.dll", "nv*.dll")
SEED_CUDA_DLL_EXTRA_NAMES = {"torch_cuda.dll", "c10_cuda.dll"}


def is_seed_cuda_dll(name: str) -> bool:
    lower = name.lower()
    if lower in SEED_CUDA_DLL_EXTRA_NAMES:
        return True
    return any(fnmatch.fnmatch(lower, pattern) for pattern in SEED_CUDA_DLL_GLOBS)


def imported_dll_names(path: Path) -> set[str]:
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        if not hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            return set()
        return {
            entry.dll.decode("ascii", "ignore").lower() for entry in pe.DIRECTORY_ENTRY_IMPORT
        }
    finally:
        pe.close()


def compute_cuda_closure(dll_files: list[Path]) -> set[str]:
    move = {f.name.lower() for f in dll_files if is_seed_cuda_dll(f.name)}
    by_name = {f.name.lower(): f for f in dll_files}

    changed = True
    while changed:
        changed = False
        for name, path in by_name.items():
            if name in move:
                continue
            if imported_dll_names(path) & move:
                move.add(name)
                changed = True
    return move


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not TORCH_LIB_DIR.is_dir():
        sys.exit(f"{TORCH_LIB_DIR} not found — run the PyInstaller build first.")

    if GPU_RUNTIME_STAGE_DIR.exists():
        shutil.rmtree(GPU_RUNTIME_STAGE_DIR)
    GPU_RUNTIME_STAGE_DIR.mkdir(parents=True)

    dropped_lib_bytes = 0
    for entry in sorted(TORCH_LIB_DIR.iterdir()):
        # .lib files are link-time-only (consumed by a linker, never by the
        # OS's DLL loader) - PyInstaller's collect_all() swept them in
        # regardless. Nothing in a frozen app touches them at runtime, so
        # drop them entirely rather than shipping them in either package.
        if entry.is_file() and entry.suffix == ".lib":
            dropped_lib_bytes += entry.stat().st_size
            entry.unlink()

    dll_files = [f for f in TORCH_LIB_DIR.iterdir() if f.is_file() and f.suffix == ".dll"]
    to_move = compute_cuda_closure(dll_files)

    if not to_move:
        sys.exit(
            "No CUDA DLLs found to move — was this build run against a "
            "non-CUDA torch wheel?"
        )

    for f in dll_files:
        if f.name.lower() in to_move:
            shutil.move(str(f), str(GPU_RUNTIME_STAGE_DIR / f.name))

    print(f"Moved {len(to_move)} CUDA runtime files into {GPU_RUNTIME_STAGE_DIR}:")
    for name in sorted(to_move):
        print(f"  {name}")
    print(f"Dropped {dropped_lib_bytes / 1e6:.0f}MB of unused link-time .lib files")

    if GPU_RUNTIME_ZIP.exists():
        GPU_RUNTIME_ZIP.unlink()
    with zipfile.ZipFile(GPU_RUNTIME_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(GPU_RUNTIME_STAGE_DIR.iterdir()):
            zf.write(f, arcname=f.name)

    version = json.loads(ELECTRON_PACKAGE_JSON.read_text())["version"]
    manifest = {
        "version": version,
        "filename": GPU_RUNTIME_ZIP.name,
        "sha256": sha256_of(GPU_RUNTIME_ZIP),
        "sizeBytes": GPU_RUNTIME_ZIP.stat().st_size,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    base_size = sum(f.stat().st_size for f in DIST_DIR.rglob("*") if f.is_file())
    print(f"Base install (dist/fisheye-ui-backend): {base_size / 1e9:.2f}GB")
    print(f"Wrote {GPU_RUNTIME_ZIP} ({manifest['sizeBytes'] / 1e9:.2f}GB)")
    print(f"Wrote {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
