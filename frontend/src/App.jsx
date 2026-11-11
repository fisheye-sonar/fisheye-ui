import { useEffect, useState } from 'react'
import SubmitForm from './components/SubmitForm'
import ProgressView from './components/ProgressView'
import TelemetryDialog from './components/TelemetryDialog'
import { telemetryChoiceLabel } from './components/telemetryUtils'

export default function App() {
  const [view, setView] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('job') ? 'progress' : 'form'
  })
  const [jobId, setJobId] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('job') || null
  })
  const [appVersion, setAppVersion] = useState(null)
  // GET /settings/telemetry response - stays null when telemetry is turned
  // off for this deployment (/platform's telemetry_enabled), which hides the
  // dialog and footer link entirely.
  const [telemetrySettings, setTelemetrySettings] = useState(null)
  const [telemetryDialogOpen, setTelemetryDialogOpen] = useState(false)

  // Fetched once here (rather than threaded through SubmitForm/ProgressView)
  // so the version tag renders the same way regardless of which view is active.
  useEffect(() => {
    let cancelled = false
    fetch('/platform')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (cancelled) return
        if (typeof data?.app_version === 'string') setAppVersion(data.app_version)
        if (data?.telemetry_enabled !== true) return
        return fetch('/settings/telemetry')
          .then(res => (res.ok ? res.json() : null))
          .then(settings => {
            if (cancelled || !settings) return
            setTelemetrySettings(settings)
            // First launch: no choice saved yet, so ask.
            if (settings.choice === null) setTelemetryDialogOpen(true)
          })
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  function handleJobCreated(id) {
    setJobId(id)
    setView('progress')
    window.history.pushState({}, '', `?job=${id}`)
  }

  function handleTelemetrySaved(settings) {
    setTelemetrySettings(settings)
    setTelemetryDialogOpen(false)
  }

  function handleBack() {
    setView('form')
    window.history.pushState({}, '', window.location.pathname)
  }

  return (
    <>
      {view === 'form'
        ? <SubmitForm onJobCreated={handleJobCreated} />
        : <ProgressView jobId={jobId} onBack={handleBack} />}
      <div className="fixed bottom-2 right-3 flex items-center gap-3 text-xs text-gray-400">
        {telemetrySettings && (
          <span>
            Usage reporting: {telemetryChoiceLabel(telemetrySettings.choice)} ·{' '}
            <button
              type="button"
              onClick={() => setTelemetryDialogOpen(true)}
              className="underline hover:text-gray-600"
            >
              Change
            </button>
          </span>
        )}
        {appVersion && <span className="select-none">v{appVersion}</span>}
      </div>
      {telemetryDialogOpen && telemetrySettings && (
        <TelemetryDialog
          settings={telemetrySettings}
          onSaved={handleTelemetrySaved}
          // No way to close without choosing at first launch - see TelemetryDialog.
          onClose={telemetrySettings.choice === null ? undefined : () => setTelemetryDialogOpen(false)}
        />
      )}
    </>
  )
}