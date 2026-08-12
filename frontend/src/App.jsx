import { useEffect, useState } from 'react'
import SubmitForm from './components/SubmitForm'
import ProgressView from './components/ProgressView'

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

  // Fetched once here (rather than threaded through SubmitForm/ProgressView)
  // so the version tag renders the same way regardless of which view is active.
  useEffect(() => {
    let cancelled = false
    fetch('/platform')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (!cancelled && typeof data?.app_version === 'string') setAppVersion(data.app_version)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  function handleJobCreated(id) {
    setJobId(id)
    setView('progress')
    window.history.pushState({}, '', `?job=${id}`)
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
      {appVersion && (
        <span className="fixed bottom-2 right-3 text-xs text-gray-400 select-none">
          v{appVersion}
        </span>
      )}
    </>
  )
}