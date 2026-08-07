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
// and archive this module consumes.

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

async function installFromZip(zipPath, manifest, onProgress) {
  const ok = await verifySha256(zipPath, manifest.sha256, onProgress)
  if (!ok) throw new Error('Downloaded file failed checksum verification')

  onProgress({ phase: 'extracting' })
  await extract(zipPath, { dir: torchLibDir() })

  fs.writeFileSync(
    markerPath(),
    JSON.stringify({ version: app.getVersion(), installedAt: new Date().toISOString() })
  )
}

async function runDownloadSetup(onProgress) {
  const manifest = loadManifest()
  const url = `https://github.com/${GITHUB_REPO}/releases/download/v${app.getVersion()}/${manifest.filename}`
  const tmpPath = path.join(app.getPath('temp'), manifest.filename)

  try {
    await downloadToFile(url, tmpPath, onProgress)
    await installFromZip(tmpPath, manifest, onProgress)
  } finally {
    fs.rm(tmpPath, { force: true }, () => {})
  }
}

async function runFileSetup(filePath, onProgress) {
  const manifest = loadManifest()
  await installFromZip(filePath, manifest, onProgress)
}

module.exports = { isGpuRuntimeInstalled, runDownloadSetup, runFileSetup }
