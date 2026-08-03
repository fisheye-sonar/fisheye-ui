const { app } = require('electron')
const https = require('https')

const GITHUB_REPO = 'fisheye-sonar/fisheye-ui'

function githubGet(path) {
  return new Promise((resolve, reject) => {
    const req = https.get(
      `https://api.github.com${path}`,
      { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'FishEye' } },
      res => {
        let body = ''
        res.on('data', chunk => (body += chunk))
        res.on('end', () => {
          try {
            resolve({ statusCode: res.statusCode, json: JSON.parse(body) })
          } catch (err) {
            reject(err)
          }
        })
      }
    )
    req.on('error', reject)
  })
}

// `/releases/latest` only ever returns the newest non-prerelease release, so
// it 404s while the project has published nothing but prereleases (e.g.
// during the 1.0.0-beta.x cycle, before the first stable tag exists). Fall
// back to the full releases list — sorted newest-first by GitHub — in that
// case so beta users still get notified about newer betas. Once a stable
// release exists, `/releases/latest` finds it and this fallback never runs.
async function fetchLatestRelease() {
  const latest = await githubGet(`/repos/${GITHUB_REPO}/releases/latest`)
  if (latest.statusCode === 200) return latest.json
  if (latest.statusCode !== 404) {
    throw new Error(`GitHub API returned ${latest.statusCode}`)
  }

  const all = await githubGet(`/repos/${GITHUB_REPO}/releases`)
  if (all.statusCode !== 200) {
    throw new Error(`GitHub API returned ${all.statusCode}`)
  }
  const newest = all.json.find(r => !r.draft)
  if (!newest) throw new Error('No releases found')
  return newest
}

// Parses tags in Electron's own release-naming convention: "vX.Y.Z" or
// "vX.Y.Z-beta.N" (also covers "-alpha.N", "-nightly.N", etc.).
function parseVersion(versionString) {
  const [core, prerelease] = versionString.replace(/^v/, '').split('-')
  const [major, minor, patch] = core.split('.').map(Number)
  return { major, minor, patch, prerelease: prerelease || null }
}

function isNewer(latestTag, currentVersion) {
  const latest = parseVersion(latestTag)
  const current = parseVersion(currentVersion)

  if (latest.major !== current.major) return latest.major > current.major
  if (latest.minor !== current.minor) return latest.minor > current.minor
  if (latest.patch !== current.patch) return latest.patch > current.patch

  // Same major.minor.patch: per semver, a release with no prerelease suffix
  // outranks one with (e.g. "1.0.0" > "1.0.0-beta.1").
  if (!latest.prerelease && !current.prerelease) return false
  if (!latest.prerelease) return true
  if (!current.prerelease) return false

  // Both are prereleases (e.g. "beta.1" vs "beta.2") — compare dot-separated
  // parts left to right, numerically where both sides are numeric.
  const latestParts = latest.prerelease.split('.')
  const currentParts = current.prerelease.split('.')
  for (let i = 0; i < Math.max(latestParts.length, currentParts.length); i++) {
    const l = latestParts[i]
    const c = currentParts[i]
    if (l === undefined) return false
    if (c === undefined) return true
    if (l === c) continue
    const lNum = Number(l)
    const cNum = Number(c)
    if (!Number.isNaN(lNum) && !Number.isNaN(cNum)) return lNum > cNum
    return l > c
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