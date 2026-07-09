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

  if (view === 'form') return <SubmitForm onJobCreated={handleJobCreated} />

  return <ProgressView jobId={jobId} onBack={handleBack} />
}