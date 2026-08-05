import { useEffect, useReducer, useRef, useState } from 'react'
import {
  applyProgressEvent,
  deriveFileCounts,
  formatConfigLines,
  formatLogEntry,
  initialProgressState,
} from './progressUtils'
import ResultsPanel from './ResultsPanel'
import UpdateBanner from './UpdateBanner'

export default function ProgressView({ jobId, onBack }) {
  const [progress, dispatch] = useReducer(applyProgressEvent, initialProgressState())
  const [configLines, setConfigLines] = useState([])
  const [showDetails, setShowDetails] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const logRef = useRef(null)
  const doneRef = useRef(false)

  useEffect(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/jobs/${jobId}/stream`
    const ws = new WebSocket(wsUrl)

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.event === 'done') doneRef.current = true
      dispatch(data)
    }

    let cleaned = false

    ws.onerror = () => {
      if (!doneRef.current && !cleaned) dispatch({ event: '__connection_lost', error: 'Lost connection to server' })
    }

    return () => {
      cleaned = true
      ws.close()
    }
  }, [jobId])

  useEffect(() => {
    let cancelled = false
    fetch(`/jobs/${jobId}`)
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (cancelled || !data) return
        setConfigLines(formatConfigLines(data.config))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [jobId])

  const {
    stage, detecting, detectPct, detectFrames,
    filesComplete, filesFailed, filesTotal, logEntries,
    completed, cancelled, error,
  } = progress

  const isTerminal = cancelled || completed || !!error
  const [otherJobActive, setOtherJobActive] = useState(false)

  // Same shared-GPU signal as the submit form, excluding this job itself so
  // it only flags when a *different* job is also running - otherwise this
  // job's own RUNNING status would always trip it.
  useEffect(() => {
    if (isTerminal) return
    let cancelled = false
    const checkActive = () => {
      fetch(`/jobs/active?exclude_job_id=${encodeURIComponent(jobId)}`)
        .then(res => (res.ok ? res.json() : null))
        .then(data => { if (!cancelled && data) setOtherJobActive(data.active) })
        .catch(() => {})
    }
    checkActive()
    const interval = setInterval(checkActive, 5000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [jobId, isTerminal])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logEntries])

  async function handleCancel() {
    setCancelling(true)
    try {
      await fetch(`/jobs/${jobId}`, { method: 'DELETE' })
    } catch {
      // WebSocket done event will report the outcome
    } finally {
      setCancelling(false)
    }
  }

  const { filesAttempted, filesSucceeded } = deriveFileCounts(progress)

  // stage stays at its 'Connecting' default until the first real pipeline
  // event (job_started) arrives - so as long as it hasn't moved, this job
  // hasn't actually started yet. Combined with otherJobActive, that's a
  // reliable "still waiting for a slot" signal (job_manager.py's
  // MAX_CONCURRENT_JOBS) without needing to poll this job's own status.
  const queued = !isTerminal && otherJobActive && stage === 'Connecting'

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center py-12 px-4">
      <div className="w-full max-w-4xl">
        <div className="mb-8 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
            <p className="text-gray-500 mt-1">
              {cancelled ? 'Job cancelled.' : error ? 'Job failed.' : completed ? 'Job complete.' : queued ? 'Waiting to start…' : 'Running inference…'}
            </p>
          </div>
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors mt-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            New job
          </button>
        </div>

        <UpdateBanner />

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
          <div>
            <div className="flex justify-between items-baseline text-sm mb-2">
              <span className="font-medium text-gray-700">{queued ? 'Waiting' : stage}</span>
              <span className="flex items-center gap-2 text-gray-400 tabular-nums">
                {filesTotal > 1 && (
                  <span>
                    {Math.min(filesAttempted + (isTerminal ? 0 : 1), filesTotal)}/{filesTotal} files
                  </span>
                )}
                {detecting && detectFrames && (
                  <span>{detectFrames.current}/{detectFrames.total} frames</span>
                )}
              </span>
            </div>

            {/* Fish + bar container — pt-5 reserves space for the fish above the bar */}
            <div className="relative pt-5">
              {!isTerminal && (
                <div
                  className="absolute top-0 pointer-events-none"
                  style={{
                    left: detecting ? `${detectPct}%` : '0%',
                    transform: detecting ? 'translateX(-50%)' : 'translateX(0)',
                    transition: 'left 0.4s ease-out',
                    animation: 'swim 0.9s ease-in-out infinite',
                  }}
                >
                  <img src="/fisheye_blue_combined.svg" alt="" className="w-8 h-auto" />
                </div>
              )}
              <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                {detecting ? (
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${detectPct}%` }}
                  />
                ) : isTerminal ? (
                  <div className={`h-2 w-full rounded-full ${cancelled ? 'bg-gray-300' : error ? 'bg-red-400' : 'bg-blue-600'}`} />
                ) : (
                  <div className="h-2 w-full rounded-full bg-blue-200 animate-pulse" />
                )}
              </div>
            </div>
          </div>

          {filesComplete > 0 && filesTotal === 0 && (
            <p className="text-sm text-gray-500">
              {filesComplete} {filesComplete === 1 ? 'file' : 'files'} processed
            </p>
          )}

          {otherJobActive && !isTerminal && (
            <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
              {queued
                ? "Another job is currently processing on this computer. Yours will start automatically once it's done."
                : 'Another job is currently processing on this computer too. Processing time may increase since they\'re running at the same time.'}
            </p>
          )}

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
          )}

          {cancelled && (
            <p className="text-sm text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
              Job was cancelled. No output files were saved.
            </p>
          )}

          {(completed || error) && filesTotal > 0 && (
            <div className="flex gap-3">
              <div className="flex-1 rounded-lg bg-green-50 px-3 py-2">
                <div className="text-lg font-semibold text-green-700 tabular-nums">{filesSucceeded}</div>
                <div className="text-xs text-green-700">successful</div>
              </div>
              <div className="flex-1 rounded-lg bg-gray-50 px-3 py-2">
                <div className="text-lg font-semibold text-gray-500 tabular-nums">{filesFailed}</div>
                <div className="text-xs text-gray-500">not successful</div>
              </div>
            </div>
          )}

          {completed && <ResultsPanel jobId={jobId} />}

          {(configLines.length > 0 || logEntries.length > 0) && (
            <div>
              <button
                onClick={() => setShowDetails(v => !v)}
                className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                {showDetails ? 'Hide log' : 'Show log'}
              </button>
              {showDetails && (
                <div ref={logRef} className="mt-2 max-h-56 overflow-y-auto space-y-1.5 text-xs bg-gray-50 rounded-lg p-3">
                  {configLines.length > 0 && (
                    <div className="pb-1.5 mb-1.5 border-b border-gray-200 space-y-1">
                      {configLines.map((line, i) => (
                        <div key={i} className="text-gray-600">{line}</div>
                      ))}
                    </div>
                  )}
                  {logEntries.map((entry, i) => (
                    <div
                      key={i}
                      className={
                        entry.level === 'warning' ? 'text-amber-600' :
                        entry.level === 'error' ? 'text-red-600' :
                        'text-gray-500'
                      }
                    >
                      {formatLogEntry(entry)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {!isTerminal && (
            <div className="flex justify-end pt-1">
              <button
                onClick={handleCancel}
                disabled={cancelling}
                className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 hover:text-gray-900 disabled:opacity-50 transition-colors"
              >
                {cancelling ? 'Cancelling…' : 'Cancel job'}
              </button>
            </div>
          )}

          {isTerminal && (
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onBack}
                className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
              >
                Start new job
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}