import { useEffect, useState } from 'react'

// Only rendered inside the Electron app — window.fisheyeElectron isn't
// exposed when running in a plain browser tab (poetry run fisheye-ui).
export default function UpdateBanner() {
  const [update, setUpdate] = useState(null)

  useEffect(() => {
    if (!window.fisheyeElectron?.onUpdateAvailable) return
    window.fisheyeElectron.onUpdateAvailable(setUpdate)
  }, [])

  if (!update) return null

  return (
    <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-6 flex items-center justify-between gap-4">
      <p>A new version of FishEye is available ({update.version}).</p>
      <div className="flex items-center gap-4 shrink-0">
        <button
          onClick={() => window.fisheyeElectron.openExternal(update.url)}
          className="font-medium underline hover:text-amber-900"
        >
          Download
        </button>
        <button onClick={() => setUpdate(null)} className="text-amber-700 hover:text-amber-900">
          Dismiss
        </button>
      </div>
    </div>
  )
}