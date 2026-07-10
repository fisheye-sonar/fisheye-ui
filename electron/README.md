# FishEye Electron shell

Wraps the FishEye UI web app (FastAPI backend + React frontend) in a native
desktop shell. The Electron main process spawns the backend as a child
process, waits for it to become healthy, then opens a window pointed at it.

## Prerequisites (both dev and build)

The frontend must be built and the backend must be bundled with PyInstaller
before Electron can run — `main.js` looks for a real binary, it doesn't run
the Python source directly. From the repo root:

```bash
cd frontend && npm run build && cd ..

poetry run pyinstaller packaging/pyinstaller/fisheye_ui.spec --noconfirm \
  --distpath packaging/pyinstaller/dist \
  --workpath packaging/pyinstaller/build
```

Re-run the frontend build after any frontend change, and re-run PyInstaller
after any backend/Python change. Both are gitignored build outputs.

## Dev mode

Runs Electron directly against the local PyInstaller output (no packaging
step). Fastest way to iterate.

```bash
cd electron
npm install        # first time only
npm start
```

## Building the final app (macOS)

Produces a signed-nothing, double-clickable
`.app`, plus a `.dmg` and `.zip` for distribution, in `electron/release/`.

```bash
cd electron
npm run build:mac
```

Output:
- `release/mac-arm64/FishEye.app` — run directly, e.g. to smoke-test:
  `release/mac-arm64/FishEye.app/Contents/MacOS/FishEye`
- `release/FishEye-<version>-arm64.dmg` — user build
- `release/FishEye-<version>-arm64-mac.zip`

The build embeds the PyInstaller backend as an `extraResource` (see the
`build.extraResources` field in `package.json`), landing at
`FishEye.app/Contents/Resources/backend/`. `main.js`'s `backendPath()`
already branches on `app.isPackaged` to find it there instead of the dev-mode
relative path — no changes needed between dev and packaged runs.

Currently unsigned: macOS Gatekeeper will show an "unidentified developer" or a corruption
warning on first launch (right-click → Open bypasses it). Code
signing/notarization is a later step (needs a paid Apple Developer
certificate). If that doesn't work, open the terminal and run: `xattr -cr /path/to/FishEye.app `