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
})