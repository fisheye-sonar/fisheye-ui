const { app } = require('electron')
const https = require('https')
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const extract = require('extract-zip')
const { GITHUB_REPO } = require('./updateCheck')

// Windows only: the CUDA/cuDNN libraries are kept out of the NSIS installer
// (electron-builder's bundled makensis can't compress a payload over ~2GB)
// and fetched into place here on first launch instead. See
// packaging/pyinstaller/split_gpu_runtime.py, which produces the manifest
// and archives this module consumes. The runtime is split into multiple
// zip parts because GitHub itself rejects release assets over 2GB - the
// whole thing zipped as one file is already ~2.3GB.

function backendDir() {
  return path.join(process.resourcesPath, 'backend')
}

function torchLibDir() {
  return path.join(backendDir(), '_internal', 'torch', 'lib')
}

function markerPath() {
  return path.join(backendDir(), '_internal', '.gpu-runtime-installed')
}

function manifestPath() {
  return path.join(__dirname, 'resources', 'gpu-runtime.manifest.json')
}

function loadManifest() {
  return JSON.parse(fs.readFileSync(manifestPath(), 'utf8'))
}

function isGpuRuntimeInstalled() {
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath(), 'utf8'))
    return marker.version === app.getVersion()
  } catch {
    return false
  }
}

function downloadToFile(url, destPath, onProgress) {
  return new Promise((resolve, reject) => {
    const request = requestUrl => {
      https
        .get(requestUrl, { headers: { 'User-Agent': 'FishEye' } }, res => {
          // GitHub release assets 302 to a signed storage URL - Node's
          // https.get doesn't follow redirects on its own.
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            res.resume()
            request(res.headers.location)
            return
          }
          if (res.statusCode !== 200) {
            reject(new Error(`Download failed: HTTP ${res.statusCode}`))
            return
          }
          const total = Number(res.headers['content-length']) || 0
          let downloaded = 0
          const file = fs.createWriteStream(destPath)
          res.on('data', chunk => {
            downloaded += chunk.length
            onProgress({ phase: 'downloading', downloaded, total })
          })
          res.pipe(file)
          file.on('finish', () => file.close(resolve))
          file.on('error', reject)
          res.on('error', reject)
        })
        .on('error', reject)
    }
    request(url)
  })
}

function verifySha256(filePath, expectedHex, onProgress) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256')
    const stream = fs.createReadStream(filePath)
    let hashed = 0
    const total = fs.statSync(filePath).size
    stream.on('data', chunk => {
      hash.update(chunk)
      hashed += chunk.length
      onProgress({ phase: 'verifying', downloaded: hashed, total })
    })
    stream.on('end', () => resolve(hash.digest('hex') === expectedHex))
    stream.on('error', reject)
  })
}

// Verifies and extracts a single part's zip into torchLibDir(). Does NOT
// write the marker file - that only happens once every part has succeeded,
// see runDownloadSetup/runFileSetup below.
async function installPart(zipPath, part, onProgress) {
  const ok = await verifySha256(zipPath, part.sha256, onProgress)
  if (!ok) throw new Error(`${part.filename} failed checksum verification`)

  onProgress({ phase: 'extracting' })
  await extract(zipPath, { dir: torchLibDir() })
}

function markInstalled() {
  fs.writeFileSync(
    markerPath(),
    JSON.stringify({ version: app.getVersion(), installedAt: new Date().toISOString() })
  )
}

async function runDownloadSetup(onProgress) {
  const manifest = loadManifest()
  const { parts } = manifest

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    const url = `https://github.com/${GITHUB_REPO}/releases/download/v${app.getVersion()}/${part.filename}`
    const tmpPath = path.join(app.getPath('temp'), part.filename)
    const partProgress = p => onProgress({ ...p, partIndex: i + 1, totalParts: parts.length })

    try {
      await downloadToFile(url, tmpPath, partProgress)
      await installPart(tmpPath, part, partProgress)
    } finally {
      fs.rm(tmpPath, { force: true }, () => {})
    }
  }

  markInstalled()
}

// filePaths: array of local paths the user picked (order doesn't matter -
// each is matched back to its manifest part by filename), one per part.
async function runFileSetup(filePaths, onProgress) {
  const manifest = loadManifest()
  const { parts } = manifest

  const byFilename = new Map(filePaths.map(p => [path.basename(p), p]))
  const missing = parts.filter(part => !byFilename.has(part.filename))
  if (missing.length > 0) {
    throw new Error(
      `Missing file(s): ${missing.map(p => p.filename).join(', ')}. ` +
        `Select all ${parts.length} gpu-runtime part files together.`
    )
  }

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    const filePath = byFilename.get(part.filename)
    const partProgress = p => onProgress({ ...p, partIndex: i + 1, totalParts: parts.length })
    await installPart(filePath, part, partProgress)
  }

  markInstalled()
}

module.exports = { isGpuRuntimeInstalled, runDownloadSetup, runFileSetup }
