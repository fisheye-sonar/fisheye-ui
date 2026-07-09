import { useEffect, useRef, useState } from 'react'

function FishIcon({ className, style }) {
  return (
    <svg viewBox="0 0 40 24" fill="currentColor" className={className} style={style} xmlns="http://www.w3.org/2000/svg">
      <path d="M10 12 L0 4 L3 12 L0 20 Z" />
      <ellipse cx="24" cy="12" rx="16" ry="9" />
      <circle cx="33" cy="9" r="2.5" fill="white" opacity="0.9" />
      <circle cx="34" cy="9" r="1.2" />
      <path d="M18 5 C22 1 28 1 30 5" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.5" strokeLinecap="round" />
    </svg>
  )
}

const STAGE_LABELS = {
  job_started: 'Starting',
  initialized_detector: 'Loading model',
  initialized_dataloader: 'Loading file',
  initialized_tracker: 'Tracking',
  skip_length_estimation: 'Tracking',
  initialized_counter: 'Counting',
  processed_file_stats: 'Processing',
  exported_detailed_csv: 'Exporting',
  exported_summary_csv: 'Exporting',
  exported_fc_txt: 'Exporting',
  job_finished: 'Finishing',
}

function parseDetectorProgress(event) {
  const match = event?.match(/Progress:\s+([\d.]+)%\s+\((\d+)\/(\d+)\)/)
  if (!match) return null
  return { pct: parseFloat(match[1]), current: parseInt(match[2], 10), total: parseInt(match[3], 10) }
}

function formatLogEntry(data) {
  switch (data.event) {
    case 'job_started':
      return data.detector_version
        ? `Job started · detector v${data.detector_version}`
        : 'Job started'
    case 'initialized_detector':
      return 'Detection model loaded'
    case 'initialized_dataloader':
      return `Loading ${data.dataset_size?.toLocaleString() ?? '?'} frames`
    case 'initialized_tracker':
      return 'Tracker ready'
    case 'initialized_counter':
      return 'Counter ready'
    case 'processed_file_stats':
      return `File complete · Total final count ${data.num_counts ?? 0}`
    case 'no_counts':
      return `No fish detected · ${data.file_path ? data.file_path.split('/').pop() : 'file'}`
    case 'length_estimation_complete':
      return `Length estimation · ${data.fish_with_valid_lengths}/${data.total_fish} fish measured`
    case 'skip_length_estimation':
      return data.message ?? 'Length estimation skipped'
    case 'exported_detailed_csv':
      return 'Exported detailed CSV'
    case 'exported_summary_csv':
      return 'Exported summary CSV'
    case 'exported_fc_txt':
      return 'Exported FC file'
    case 'safe_execution_exception':
      return `File failed · retrying (attempt ${data.attempt ?? '?'})`
    case 'safe_execution_failed':
      return `File failed after ${data.retries ?? 3} attempts · skipped`
    case 'job_finished':
      return data.duration_sec != null
        ? `Job complete · ${Math.round(data.duration_sec)}s`
        : 'Job complete'
    default:
      return data.event
  }
}

export default function ProgressView({ jobId, onComplete, onBack }) {
  const [stage, setStage] = useState('Connecting')
  const [detecting, setDetecting] = useState(false)
  const [detectPct, setDetectPct] = useState(0)
  const [detectFrames, setDetectFrames] = useState(null)
  const [filesComplete, setFilesComplete] = useState(0)
  const [filesFailed, setFilesFailed] = useState(0)
  const [filesTotal, setFilesTotal] = useState(0)
  const [logEntries, setLogEntries] = useState([])
  const [showDetails, setShowDetails] = useState(false)
  const [error, setError] = useState(null)
  const [cancelled, setCancelled] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [jobFinished, setJobFinished] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const logRef = useRef(null)
  const doneRef = useRef(false)
  const datasetSizeRef = useRef(null)
  const batchSizeRef = useRef(null)

  useEffect(() => {
    const wsUrl = `ws://${window.location.host}/jobs/${jobId}/stream`
    const ws = new WebSocket(wsUrl)

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)

      if (data.event === 'done') {
        doneRef.current = true
        setDetecting(false)
        if (data.status === 'completed') {
          setStage('Complete')
          setCompleted(true)
        } else if (data.status === 'cancelled') {
          setStage('Cancelled')
          setCancelled(true)
        } else {
          setStage('Failed')
          setError(data.error ?? 'Job failed')
        }
        return
      }

      if (data.event === 'files_discovered') {
        setFilesTotal(data.num_files ?? 0)
        return
      }

      // Detection progress — update bar only, don't log.
      // The (current/total) in the debug message counts batches, not frames,
      // so convert to a frame count using the batch/dataset size from
      // initialized_dataloader. Last batch may be a partial one, so clamp to
      // the dataset size rather than overshooting.
      const progress = parseDetectorProgress(data.event)
      if (progress !== null) {
        setDetecting(true)
        setDetectPct(progress.pct)
        const datasetSize = datasetSizeRef.current
        const batchSize = batchSizeRef.current
        setDetectFrames(
          datasetSize && batchSize
            ? { current: Math.min(progress.current * batchSize, datasetSize), total: datasetSize }
            : null
        )
        return
      }

      // File completion resets the detection bar for the next file
      if (data.event === 'processed_file_stats' || data.event === 'no_counts') {
        setFilesComplete(prev => prev + 1)
        setDetecting(false)
        setDetectPct(0)
        setDetectFrames(null)
      }

      // A file that exhausted its retries is done being attempted — count it
      // separately rather than inferring failures from filesTotal - filesComplete.
      if (data.event === 'safe_execution_failed' && data.function === '_run') {
        setFilesFailed(prev => prev + 1)
        setDetecting(false)
        setDetectPct(0)
        setDetectFrames(null)
      }

      if (data.event === 'initialized_dataloader') {
        setDetecting(false)
        setDetectPct(0)
        setDetectFrames(null)
        datasetSizeRef.current = data.dataset_size ?? null
        batchSizeRef.current = data.batch_size ?? null
      }

      // job_finished means the pipeline attempted every discovered file, even
      // if the job is later marked failed for an unrelated reason (e.g. the
      // summary CSV couldn't be found) — a reliable point to trust filesTotal.
      if (data.event === 'job_finished') {
        setJobFinished(true)
      }

      if (STAGE_LABELS[data.event]) {
        setStage(STAGE_LABELS[data.event])
      }

      if (data.level !== 'debug') {
        setLogEntries(prev => [...prev, data])
      }
    }

    let cleaned = false

    ws.onerror = () => {
      if (!doneRef.current && !cleaned) setError('Lost connection to server')
    }

    return () => {
      cleaned = true
      ws.close()
    }
  }, [jobId])

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

  const isTerminal = cancelled || completed || !!error
  // filesComplete undercounts successes: the pipeline's per-file stats logging
  // is wrapped in a bare except-pass, so a file can succeed and export without
  // ever emitting processed_file_stats/no_counts. filesFailed (from the retry
  // decorator's terminal safe_execution_failed log) doesn't have that gap, and
  // job_finished guarantees every discovered file was attempted (regardless of
  // whether the job is later marked completed or failed) — so once we've seen
  // it, derive successes from the total instead of counting them directly.
  const filesAttempted = filesComplete + filesFailed
  const filesSucceeded = jobFinished ? Math.max(filesTotal - filesFailed, 0) : filesComplete

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center py-12 px-4">
      <div className="w-full max-w-xl">
        <div className="mb-8 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
            <p className="text-gray-500 mt-1">
              {cancelled ? 'Job cancelled.' : error ? 'Job failed.' : completed ? 'Job complete.' : 'Running inference…'}
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

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
          <div>
            <div className="flex justify-between items-baseline text-sm mb-2">
              <span className="font-medium text-gray-700">{stage}</span>
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
                  <FishIcon className="w-8 h-auto text-blue-500" />
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

          {logEntries.length > 0 && (
            <div>
              <button
                onClick={() => setShowDetails(v => !v)}
                className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                {showDetails ? 'Hide details' : 'Show details'}
              </button>
              {showDetails && (
                <div ref={logRef} className="mt-2 max-h-56 overflow-y-auto space-y-1.5 text-xs bg-gray-50 rounded-lg p-3">
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
              {completed && (
                <button
                  onClick={() => onComplete(jobId, 'completed', { filesSucceeded, filesFailed, filesTotal })}
                  className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
                >
                  View results
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}