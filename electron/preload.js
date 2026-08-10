const { contextBridge, webUtils, ipcRenderer } = require('electron')

// Electron 32+ removed the non-standard File.path property from
// drag-and-dropped files; webUtils.getPathForFile is the replacement, but
// it's only reachable from the main/preload process, hence this bridge.
// Works for dropped folders too (returns the folder's path).
contextBridge.exposeInMainWorld('fisheyeElectron', {
  getPathForFile: file => webUtils.getPathForFile(file),

  // Native file/folder pickers (see main.js) - work the same on every
  // platform, unlike the backend's AppleScript/zenity routes which have no
  // Windows equivalent. Resolves to a path string, or null if cancelled.
  pickFile: () => ipcRenderer.invoke('pick-file'),
  pickDirectory: () => ipcRenderer.invoke('pick-directory'),

  // Update notification: main process pushes 'update-available' once (see
  // updateCheck.js) after checking GitHub releases; the renderer shows it
  // as an in-app banner instead of a native OS dialog, to stay consistent
  // with the rest of the UI.
  onUpdateAvailable: callback => {
    ipcRenderer.on('update-available', (_event, payload) => callback(payload))
  },
  // shell isn't reachable directly from a sandboxed preload script, so this
  // is routed through the main process instead (see main.js's ipcMain.handle).
  openExternal: url => ipcRenderer.invoke('open-external', url),

  // Windows-only first-run GPU (CUDA) runtime setup, exercised only when
  // gpuSetup.js's isGpuRuntimeInstalled() says the CUDA libraries weren't
  // downloaded yet (see setup.html/setup.js). Errors are reported via
  // onGpuSetupError rather than a rejected promise, since the setup itself
  // runs to completion (success or failure) inside the ipcMain.handle.
  startGpuSetupDownload: () => ipcRenderer.invoke('gpu-setup-download'),
  // The runtime ships as multiple zip parts (GitHub rejects release assets
  // over 2GB), so this takes/returns an array of paths, not a single one.
  startGpuSetupFromFiles: filePaths => ipcRenderer.invoke('gpu-setup-from-files', filePaths),
  pickGpuRuntimeFiles: () => ipcRenderer.invoke('pick-gpu-runtime-files'),
  onGpuSetupProgress: callback => {
    ipcRenderer.on('gpu-setup-progress', (_event, payload) => callback(payload))
  },
  onGpuSetupError: callback => {
    ipcRenderer.on('gpu-setup-error', (_event, payload) => callback(payload))
  },
  onGpuSetupComplete: callback => {
    ipcRenderer.on('gpu-setup-complete', () => callback())
  },
})