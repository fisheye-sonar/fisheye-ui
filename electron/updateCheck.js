const { app } = require('electron')
const https = require('https')

const GITHUB_REPO = 'electron/electron' // TEMP: swap back after testing

function fetchLatestRelease() {
  return new Promise((resolve, reject) => {
    const req = https.get(
      `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`,
      { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'FishEye' } },
      res => {
        let body = ''
        res.on('data', chunk => (body += chunk))
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`GitHub API returned ${res.statusCode}`))
            return
          }
          try {
            resolve(JSON.parse(body))
          } catch (err) {
            reject(err)
          }
        })
      }
    )
    req.on('error', reject)
  })
}

// Plain dot-separated integer comparison — releases aren't expected to use
// full semver prerelease/build tags, just "x.y.z" (with or without a "v" prefix).
function isNewer(latestTag, currentVersion) {
  const latest = latestTag.replace(/^v/, '').split('.').map(Number)
  const current = currentVersion.split('.').map(Number)
  for (let i = 0; i < Math.max(latest.length, current.length); i++) {
    const l = latest[i] || 0
    const c = current[i] || 0
    if (l !== c) return l > c
  }
  return false
}

// Notifies the given window's renderer via IPC (see preload.js /
// UpdateBanner.jsx) rather than showing a native OS dialog, so the update
// notice looks like part of the app instead of a system popup.
async function checkForUpdate(win) {
  let release
  try {
    release = await fetchLatestRelease()
  } catch (err) {
    // Offline or GitHub unreachable — fail silently, don't interrupt the user.
    console.error('Update check failed:', err)
    return
  }

  if (!isNewer(release.tag_name, app.getVersion())) return

  win.webContents.send('update-available', {
    version: release.tag_name,
    url: release.html_url,
  })
}

module.exports = { checkForUpdate }