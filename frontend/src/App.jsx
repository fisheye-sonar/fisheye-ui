import { useState } from 'react'
import SubmitForm from './components/SubmitForm'
import ProgressView from './components/ProgressView'
import ResultsView from './components/ResultsView'

export default function App() {
  const [view, setView] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('job') ? 'progress' : 'form'
  })
  const [jobId, setJobId] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('job') || null
  })
  const [resultStats, setResultStats] = useState(null)

  function handleJobCreated(id) {
    setJobId(id)
    setView('progress')
    window.history.pushState({}, '', `?job=${id}`)
  }

  function handleBack() {
    setView('form')
    setResultStats(null)
    window.history.pushState({}, '', window.location.pathname)
  }

  function handleComplete(id, status, stats) {
    if (status === 'completed') {
      setResultStats(stats ?? null)
      setView('results')
    }
  }

  if (view === 'form') return <SubmitForm onJobCreated={handleJobCreated} />
  if (view === 'progress') return <ProgressView jobId={jobId} onComplete={handleComplete} onBack={handleBack} />

  return <ResultsView jobId={jobId} stats={resultStats} onBack={handleBack} />
}