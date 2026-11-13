// Runs before every build:mac/build:win (see package.json's prebuild:*
// scripts). Bakes the usage reporting URL into telemetry-config.json, which
// ships inside the app and is read by main.js.
//
// The URL comes from FISHEYE_TELEMETRY_URL or the git-ignored .env.release
// rather than the repo, so only official release builds report to the
// FishEye team's receiver. Anyone else's build gets an empty URL, which
// turns usage reporting off entirely (no opt-in dialog) - see
// deploy/telemetry/README.md to run your own.
const fs = require('fs')
const path = require('path')

// Holds the URL on the release builder's machine (see "Usage reporting URL"
// in electron/README.md). Forks don't have it.
const ENV_FILE = path.join(__dirname, '..', '.env.release')

function urlFromEnvFile() {
  try {
    // Accepts `FISHEYE_TELEMETRY_URL=...` with or without `export` and
    // quotes, so the same file still works with `source .env.release`.
    const match = fs
      .readFileSync(ENV_FILE, 'utf8')
      .match(/^\s*(?:export\s+)?FISHEYE_TELEMETRY_URL\s*=\s*['"]?([^'"\s]*)/m)
    return match ? match[1] : ''
  } catch {
    return ''
  }
}

// An explicitly set variable wins, including an empty one, so
// `FISHEYE_TELEMETRY_URL= npm run build:mac` builds without usage reporting
// even when .env.release exists.
const url =
  'FISHEYE_TELEMETRY_URL' in process.env ? process.env.FISHEYE_TELEMETRY_URL : urlFromEnvFile()

if (url) {
  console.log(`Usage reporting URL: ${url}`)
} else {
  console.warn(
    '\n⚠️  FISHEYE_TELEMETRY_URL is not set: this build will not offer usage reporting.\n' +
      '   For an official release, see "Usage reporting URL" in electron/README.md.\n'
  )
}
fs.writeFileSync(path.join(__dirname, '..', 'telemetry-config.json'), JSON.stringify({ url }) + '\n')
