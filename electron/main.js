const { app, BrowserWindow } = require('electron')
const { spawn } = require('child_process')
const http = require('http')
const net = require('net')
const path = require('path')
const treeKill = require('tree-kill')

// app.getName() defaults to package.json's "name" field ("fisheye-ui-electron"),
// not the "FishEye" productName — override it so userData (where the backend's
// relative "logs/" dir ends up, see startBackend) uses the user-facing name.
app.setName('FishEye')

let backendProcess = null
let win = null

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
  // Packaged app: PyInstaller's onedir output ships as an extraResource.
  // Dev mode: point straight at the local PyInstaller build output.
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', 'fisheye-ui-backend')
  }
  return path.join(
    __dirname,
    '..',
    'packaging',
    'pyinstaller',
    'dist',
    'fisheye-ui-backend',
    'fisheye-ui-backend'
  )
}

function waitForHealth(port, timeoutMs = 30000) {
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
    stdio: 'inherit',
  })
  // torch's import time on first launch can be slow, hence the generous
  // waitForHealth timeout above rather than a fixed startup delay.
  await waitForHealth(port)
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
  win.loadURL(`http://127.0.0.1:${port}`)
}

app.whenReady().then(() => {
  // Packaged builds get their icon from the .icns embedded by electron-builder
  // (build.mac.icon) — dev mode otherwise falls back to the generic Electron
  // icon in the Dock, so set it explicitly here too.
  if (!app.isPackaged && process.platform === 'darwin') {
    app.dock.setIcon(path.join(__dirname, 'build-resources', 'icon.png'))
  }

  createWindow().catch(err => {
    console.error('Failed to start backend:', err)
    app.quit()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', stopBackend)