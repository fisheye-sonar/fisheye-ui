import { useState } from 'react'
import SubmitForm from './components/SubmitForm'
import ProgressView from './components/ProgressView'

export default function App() {
  const [view, setView] = useState('form')
  const [jobId, setJobId] = useState(null)

  function handleJobCreated(id) {
    setJobId(id)
    setView('progress')
  }

  function handleComplete(id, status) {
    if (status === 'completed') setView('results')
    else setView('form')
  }

  if (view === 'form') return <SubmitForm onJobCreated={handleJobCreated} />
  if (view === 'progress') return <ProgressView jobId={jobId} onComplete={handleComplete} />

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <p className="text-gray-500">Results for job {jobId} — coming soon</p>
    </div>
  )
}