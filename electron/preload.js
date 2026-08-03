// Phase 2 will expose a native file/folder picker here via contextBridge,
// so the frontend can use Electron's dialog API instead of the backend's
// AppleScript/zenity pickers (which don't support Windows).

const { contextBridge, webUtils, ipcRenderer, shell } = require('electron')

// Electron 32+ removed the non-standard File.path property from
// drag-and-dropped files; webUtils.getPathForFile is the replacement, but
// it's only reachable from the main/preload process, hence this bridge.
// Works for dropped folders too (returns the folder's path).
contextBridge.exposeInMainWorld('fisheyeElectron', {
  getPathForFile: file => webUtils.getPathForFile(file),

  // Update notification: main process pushes 'update-available' once (see
  // updateCheck.js) after checking GitHub releases; the renderer shows it
  // as an in-app banner instead of a native OS dialog, to stay consistent
  // with the rest of the UI.
  onUpdateAvailable: callback => {
    ipcRenderer.on('update-available', (_event, payload) => callback(payload))
  },
  openExternal: url => shell.openExternal(url),
})