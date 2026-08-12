# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

# torch/ultralytics/cv2 rely on dynamic imports and ship non-Python data
# files (e.g. ultralytics's .yaml configs) that PyInstaller's static
# analysis won't find on its own. `fisheye` is the ML pipeline package
# (installed as a git dependency) and has the same issue. `yolov5` is a
# separate top-level package pulled in as a `fisheye` dependency (distinct
# from `ultralytics`) whose utils/general.py reads its own source file at
# runtime to locate the repo root — without collect_all, PyInstaller only
# bundles the compiled bytecode, not that literal .py file, and it fails
# with a FileNotFoundError as soon as a job actually runs.
datas = []
binaries = []
hiddenimports = []
for pkg in ("torch", "ultralytics", "yolov5", "cv2", "fisheye"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

repo_root = os.path.dirname(os.path.dirname(SPECPATH))
static_dir = os.path.join(repo_root, "fisheye_ui", "static")
if not os.path.isdir(static_dir):
    raise SystemExit(
        f"{static_dir} not found — run `npm run build` in frontend/ before "
        "building the PyInstaller bundle."
    )
datas.append((static_dir, os.path.join("fisheye_ui", "static")))

a = Analysis(
    [os.path.join(SPECPATH, "entrypoint.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fisheye-ui-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # False (GUI subsystem) so Windows never pops up a console window when
    # Electron spawns this as a child process - a console=True bootloader
    # allocates its own console internally (AllocConsole()) whenever one
    # isn't inherited, which no amount of windowsHide/stdio piping on the
    # parent side can prevent, since that decision happens inside the
    # child itself. stdout/stderr are still fully usable via explicit pipes
    # (see main.js's startBackend) - this only affects whether an
    # automatic console window gets created, not handle availability.
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fisheye-ui-backend",
)