import { useState } from 'react'
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

  function handleJobCreated(id) {
    setJobId(id)
    setView('progress')
    window.history.pushState({}, '', `?job=${id}`)
  }

  function handleBack() {
    setView('form')
    window.history.pushState({}, '', window.location.pathname)
  }

  function handleComplete(id, status) {
    if (status === 'completed') setView('results')
  }

  if (view === 'form') return <SubmitForm onJobCreated={handleJobCreated} />
  if (view === 'progress') return <ProgressView jobId={jobId} onComplete={handleComplete} onBack={handleBack} />

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <p className="text-gray-500">Results for job {jobId} — coming soon</p>
    </div>
  )
}