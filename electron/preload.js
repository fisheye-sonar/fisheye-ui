// Phase 2 will expose a native file/folder picker here via contextBridge,
// so the frontend can use Electron's dialog API instead of the backend's
// AppleScript/zenity pickers (which don't support Windows).

const { contextBridge, webUtils } = require('electron')

// Electron 32+ removed the non-standard File.path property from
// drag-and-dropped files; webUtils.getPathForFile is the replacement, but
// it's only reachable from the main/preload process, hence this bridge.
// Works for dropped folders too (returns the folder's path).
contextBridge.exposeInMainWorld('fisheyeElectron', {
  getPathForFile: file => webUtils.getPathForFile(file),
})