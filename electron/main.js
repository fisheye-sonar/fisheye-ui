const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron')
const { spawn } = require('child_process')
const http = require('http')
const net = require('net')
const path = require('path')
const treeKill = require('tree-kill')
const { checkForUpdate } = require('./updateCheck')
const { isGpuRuntimeInstalled, runDownloadSetup, runFileSetup } = require('./gpuSetup')

// shell isn't reachable from the sandboxed preload script, so the renderer's
// "Download" click is routed through here instead (see preload.js).
ipcMain.handle('open-external', (_event, url) => shell.openExternal(url))

// Native pickers, replacing the backend's OS-specific AppleScript/zenity
// routes (fisheye_ui/routes/files.py) for anything running inside Electron.
// dialog.showOpenDialog is the same API on every platform, so this is what
// makes folder/file picking actually work on Windows (the backend route
// there just 501s - no equivalent to osascript/zenity exists) instead of
// only macOS/Linux. Registered against `win` so the dialog is a sheet/modal
// on macOS rather than a detached window.
ipcMain.handle('pick-file', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: 'Select an ARIS or DDF file',
    properties: ['openFile'],
    filters: [{ name: 'ARIS/DDF files', extensions: ['aris', 'ddf'] }],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

ipcMain.handle('pick-directory', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: 'Select a folder containing ARIS or DDF files',
    properties: ['openDirectory'],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

// --- Windows-only first-run GPU (CUDA) runtime setup, see gpuSetup.js ---

let gpuSetupWindow = null
let resolveGpuSetup = null

ipcMain.handle('pick-gpu-runtime-files', async () => {
  // The runtime ships as multiple zip parts (GitHub rejects release assets
  // over 2GB - see split_gpu_runtime.py), so this needs all of them
  // selected together, not just one file.
  const result = await dialog.showOpenDialog(gpuSetupWindow, {
    title: 'Select all FishEye GPU runtime part files',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'GPU runtime archive', extensions: ['zip'] }],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths
})

async function runGpuSetupAction(action, ...args) {
  const sendProgress = progress => gpuSetupWindow?.webContents.send('gpu-setup-progress', progress)
  try {
    await action(...args, sendProgress)
    gpuSetupWindow.webContents.send('gpu-setup-complete')
    const resolve = resolveGpuSetup
    resolveGpuSetup = null
    gpuSetupWindow.close()
    resolve()
  } catch (err) {
    gpuSetupWindow?.webContents.send('gpu-setup-error', { message: err.message })
  }
}

ipcMain.handle('gpu-setup-download', () => runGpuSetupAction(runDownloadSetup))
ipcMain.handle('gpu-setup-from-files', (_event, filePaths) => runGpuSetupAction(runFileSetup, filePaths))

// Opens the setup window and resolves once runGpuSetupAction reports
// success. Closing the window before that (user quits mid-setup) rejects
// instead, since resolveGpuSetup is still set at that point.
function openGpuSetupWindow() {
  return new Promise((resolve, reject) => {
    resolveGpuSetup = resolve
    gpuSetupWindow = new BrowserWindow({
      width: 440,
      height: 300,
      resizable: false,
      webPreferences: { preload: path.join(__dirname, 'preload.js') },
    })
    gpuSetupWindow.setMenuBarVisibility(false)
    gpuSetupWindow.loadFile(path.join(__dirname, 'setup.html'))
    gpuSetupWindow.on('closed', () => {
      gpuSetupWindow = null
      if (resolveGpuSetup) {
        resolveGpuSetup = null
        reject(new Error('Setup was closed before finishing'))
      }
    })
  })
}

// app.getName() defaults to package.json's "name" field ("fisheye-ui-electron"),
// not the "FishEye" productName — override it so userData (where the backend's
// relative "logs/" dir ends up, see startBackend) uses the user-facing name.
app.setName('FishEye')

let backendProcess = null
let win = null
// Guards window-all-closed below: closing the GPU setup window (the only
// window open at that point) would otherwise fire window-all-closed and
// quit the app before createWindow() ever gets to open the real one - a
// real race, not just a hypothetical one, since app.quit()'s shutdown can
// get ahead of the still-pending createWindow() call.
let mainWindowOpened = false

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

function backendPath() {
  // PyInstaller names the Windows binary with a .exe suffix; spawn() there
  // needs the exact filename, unlike macOS/Linux which run it extension-less.
  const exeName = process.platform === 'win32' ? 'fisheye-ui-backend.exe' : 'fisheye-ui-backend'
  // Packaged app: PyInstaller's onedir output ships as an extraResource.
  // Dev mode: point straight at the local PyInstaller build output.
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', exeName)
  }
  return path.join(
    __dirname,
    '..',
    'packaging',
    'pyinstaller',
    'dist',
    'fisheye-ui-backend',
    exeName
  )
}

function waitForHealth(port, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    function attempt() {
      const req = http.get(`http://127.0.0.1:${port}/health`, res => {
        res.resume()
        if (res.statusCode === 200) resolve()
        else retry()
      })
      req.on('error', retry)
    }
    function retry() {
      if (Date.now() > deadline) {
        reject(new Error('Backend did not become healthy in time'))
        return
      }
      setTimeout(attempt, 250)
    }
    attempt()
  })
}

async function startBackend() {
  const port = await getFreePort()
  backendProcess = spawn(backendPath(), [], {
    env: { ...process.env, FISHEYE_UI_NO_BROWSER: '1', PORT: String(port) },
    // The backend writes a relative "logs/" dir when a job runs. Without an
    // explicit cwd, a packaged/double-clicked .app inherits Electron's own
    // working directory — typically "/" — where that write fails with
    // EROFS. userData is guaranteed to exist and be writable.
    cwd: app.getPath('userData'),
    // stdio:'inherit' plus windowsHide alone doesn't suppress the console
    // window PyInstaller's console=True bootloader used to allocate on
    // Windows (fixed by building with console=False instead - see
    // packaging/pyinstaller/fisheye_ui.spec), since Electron's own GUI
    // process has no console of its own for the child to inherit in the
    // first place. Piping instead avoids needing a console handle at all;
    // forwarding the pipes below keeps `npm start`'s terminal output
    // working exactly like 'inherit' did.
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  backendProcess.stdout.on('data', chunk => process.stdout.write(chunk))
  backendProcess.stderr.on('data', chunk => process.stderr.write(chunk))

  // Without a listener, an unhandled 'error' event on a ChildProcess
  // crashes the entire Electron process instantly - no dialog, no trace,
  // it just vanishes (e.g. a just-downloaded .exe carrying Windows'
  // "Mark of the Web" getting blocked/delayed by Defender at the exact
  // moment of spawn). Racing against waitForHealth surfaces that as a
  // normal rejection the caller's try/catch can show a real dialog for,
  // instead of silently waiting out the full health-check timeout for an
  // error that already happened.
  const crashed = new Promise((_, reject) => {
    backendProcess.once('error', reject)
    backendProcess.once('exit', (code, signal) => {
      reject(new Error(`Backend exited before becoming healthy (code ${code}, signal ${signal})`))
    })
  })

  try {
    await Promise.race([waitForHealth(port), crashed])
  } finally {
    backendProcess.removeAllListeners('error')
    backendProcess.removeAllListeners('exit')
    // Keep listening for the rest of the process's life so a later crash
    // (mid-use, not just at startup) logs instead of taking the whole
    // Electron app down with it the same way.
    backendProcess.on('error', err => console.error('Backend process error:', err))
    backendProcess.on('exit', (code, signal) => {
      if (code !== 0 && code !== null) {
        console.error(`Backend exited unexpectedly (code ${code}, signal ${signal})`)
      }
    })
  }
  return port
}

function stopBackend() {
  if (backendProcess && backendProcess.pid) {
    treeKill(backendProcess.pid)
    backendProcess = null
  }
}

async function createWindow() {
  const port = await startBackend()
  win = new BrowserWindow({
    width: 1100,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  })
  mainWindowOpened = true
  win.loadURL(`http://127.0.0.1:${port}`)
  // Wait for the page (and its update-available IPC listener) to be ready
  // before sending, otherwise the event fires into nothing.
  win.webContents.once('did-finish-load', () => checkForUpdate(win))
}

app.whenReady().then(async () => {
  // Packaged builds get their icon from the .icns embedded by electron-builder
  // (build.mac.icon) — dev mode otherwise falls back to the generic Electron
  // icon in the Dock, so set it explicitly here too.
  if (!app.isPackaged && process.platform === 'darwin') {
    app.dock.setIcon(path.join(__dirname, 'build-resources', 'icon.png'))
  }

  // The CUDA libraries are kept out of the Windows installer (see
  // packaging/pyinstaller/split_gpu_runtime.py) to stay under NSIS's ~2GB
  // payload limit, and fetched here instead, once, before the backend ever
  // starts. Dev mode runs straight off the local PyInstaller output, which
  // isn't split, so this only applies to packaged Windows builds.
  if (process.platform === 'win32' && app.isPackaged && !isGpuRuntimeInstalled()) {
    try {
      await openGpuSetupWindow()
    } catch (err) {
      console.error('GPU runtime setup did not complete:', err)
      dialog.showErrorBox('FishEye setup did not finish', err.message)
      app.quit()
      return
    }
  }

  try {
    await createWindow()
  } catch (err) {
    // Silently quitting here means a slow/failed backend start looks
    // exactly like the app never opened at all, with no way to tell why -
    // show the real reason instead.
    console.error('Failed to start backend:', err)
    dialog.showErrorBox('FishEye failed to start', err.message)
    app.quit()
  }
})

app.on('window-all-closed', () => {
  // Guard against the GPU setup window (main.js's only open window at that
  // point) closing itself and firing this before createWindow() ever gets
  // to open the real one - see mainWindowOpened's declaration above. This
  // fires *asynchronously*, after native window teardown completes, by
  // which point createWindow() has typically already raced ahead and
  // called startBackend() - so stopBackend() here isn't just a premature
  // quit, it actively kills the backend startBackend() just spawned out
  // from under it. Setup failing/being aborted before mainWindowOpened
  // quits explicitly via its own try/catch in app.whenReady() instead,
  // which independently triggers stopBackend() through the 'before-quit'
  // handler below - so nothing legitimate is skipped by returning here.
  if (!mainWindowOpened) return

  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', stopBackend)