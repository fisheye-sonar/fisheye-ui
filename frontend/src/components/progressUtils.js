export const STAGE_LABELS = {
  job_started: 'Starting',
  initialized_detector: 'Loading model',
  initialized_dataloader: 'Analyzing',
  initialized_tracker: 'Tracking',
  skip_length_estimation: 'Tracking',
  initialized_counter: 'Counting',
  processed_file_stats: 'Processing',
  exported_detailed_csv: 'Exporting',
  exported_summary_csv: 'Exporting',
  exported_fc_txt: 'Exporting',
  job_finished: 'Finishing',
}

export const EXPORT_LABELS = {
  summary_csv: 'Summary CSV',
  detailed_csv: 'Detailed CSV',
  fc: 'FC',
  mot: 'MOT',
}

export const DEVICE_LABELS = {
  mps: 'Apple Silicon (MPS)',
  'cuda:0': 'NVIDIA GPU (CUDA)',
  cpu: 'CPU',
}

export function formatConfigLines(config) {
  if (!config) return []
  const model = config.platform?.model ?? {}
  return [
    `Input file/folder: ${config.input_path?.replace(/\/+$/, '').split('/').pop() || '—'}`,
    `Results folder: ${config.output_dir || 'same folder as input'}`,
    `Model weights: ${model.weights ?? '—'}`,
    `Device: ${DEVICE_LABELS[model.device] ?? model.device ?? '—'}`,
    `Upstream direction: ${config.upstream_direction ?? '—'}`,
    `Distance offset: ${config.distance_offset ?? 0} m`,
    `Export options: ${(config.export_options ?? []).map(o => EXPORT_LABELS[o] ?? o).join(', ') || '—'}`,
  ]
}

export function parseDetectorProgress(event) {
  const match = event?.match(/Progress:\s+([\d.]+)%\s+\((\d+)\/(\d+)\)/)
  if (!match) return null
  return { pct: parseFloat(match[1]), current: parseInt(match[2], 10), total: parseInt(match[3], 10) }
}

export function formatLogEntry(data) {
  switch (data.event) {
    case 'job_started':
      return data.detector_version
        ? `Job started · detector ${data.detector_version}`
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

export function initialProgressState() {
  return {
    stage: 'Connecting',
    detecting: false,
    detectPct: 0,
    detectFrames: null,
    filesComplete: 0,
    filesFailed: 0,
    filesTotal: 0,
    logEntries: [],
    jobFinished: false,
    completed: false,
    cancelled: false,
    error: null,
    done: false,
    datasetSize: null,
    batchSize: null,
  }
}

// Pure reducer over the WebSocket progress stream: (state, event) -> next
// state. Mirrors the backend's own event shape exactly, including which
// branches fall through to also update `stage`/`logEntries` below (e.g. a
// processed_file_stats event both increments filesComplete *and* sets the
// "Processing" stage *and* gets logged) rather than an early return.
export function applyProgressEvent(state, data) {
  // Synthetic client-side event (WebSocket onerror, not a server message):
  // only the error banner is shown, unlike a real 'done' event - stage,
  // detecting, and completed/cancelled are deliberately left untouched in
  // case a real 'done' still arrives afterward.
  if (data.event === '__connection_lost') {
    return { ...state, error: data.error }
  }

  if (data.event === 'done') {
    const next = { ...state, done: true, detecting: false }
    if (data.status === 'completed') {
      next.stage = 'Complete'
      next.completed = true
    } else if (data.status === 'cancelled') {
      next.stage = 'Cancelled'
      next.cancelled = true
    } else {
      next.stage = 'Failed'
      next.error = data.error ?? 'Job failed'
    }
    return next
  }

  if (data.event === 'files_discovered') {
    return { ...state, filesTotal: data.num_files ?? 0 }
  }

  // Detection progress — update the bar only, don't log. The (current/total)
  // in the debug message counts batches, not frames, so convert to a frame
  // count using the batch/dataset size from initialized_dataloader. Last
  // batch may be partial, so clamp to the dataset size rather than
  // overshooting.
  const progress = parseDetectorProgress(data.event)
  if (progress !== null) {
    const { datasetSize, batchSize } = state
    return {
      ...state,
      detecting: true,
      detectPct: progress.pct,
      detectFrames:
        datasetSize && batchSize
          ? { current: Math.min(progress.current * batchSize, datasetSize), total: datasetSize }
          : null,
    }
  }

  let next = state

  // File completion resets the detection bar for the next file.
  if (data.event === 'processed_file_stats' || data.event === 'no_counts') {
    next = {
      ...next,
      filesComplete: next.filesComplete + 1,
      detecting: false,
      detectPct: 0,
      detectFrames: null,
    }
  }

  // A file that exhausted its retries is done being attempted — count it
  // separately rather than inferring failures from filesTotal - filesComplete.
  if (data.event === 'safe_execution_failed' && data.function === '_run') {
    next = {
      ...next,
      filesFailed: next.filesFailed + 1,
      detecting: false,
      detectPct: 0,
      detectFrames: null,
    }
  }

  if (data.event === 'initialized_dataloader') {
    next = {
      ...next,
      detecting: false,
      detectPct: 0,
      detectFrames: null,
      datasetSize: data.dataset_size ?? null,
      batchSize: data.batch_size ?? null,
    }
  }

  // job_finished means the pipeline attempted every discovered file, even if
  // the job is later marked failed for an unrelated reason (e.g. the summary
  // CSV couldn't be found) — a reliable point to trust filesTotal.
  if (data.event === 'job_finished') {
    next = { ...next, jobFinished: true }
  }

  if (STAGE_LABELS[data.event]) {
    next = { ...next, stage: STAGE_LABELS[data.event] }
  }

  if (data.level !== 'debug') {
    next = { ...next, logEntries: [...next.logEntries, data] }
  }

  return next
}

// filesComplete undercounts successes: the pipeline's per-file stats logging
// is wrapped in a bare except-pass, so a file can succeed and export without
// ever emitting processed_file_stats/no_counts. filesFailed (from the retry
// decorator's terminal safe_execution_failed log) doesn't have that gap, and
// job_finished guarantees every discovered file was attempted — so once
// we've seen it, derive successes from the total instead of counting them
// directly.
export function deriveFileCounts(state) {
  const filesAttempted = state.filesComplete + state.filesFailed
  const filesSucceeded = state.jobFinished
    ? Math.max(state.filesTotal - state.filesFailed, 0)
    : state.filesComplete
  return { filesAttempted, filesSucceeded }
}
