import { describe, expect, it } from 'vitest'
import {
  applyProgressEvent,
  deriveFileCounts,
  formatConfigLines,
  formatLogEntry,
  initialProgressState,
  parseDetectorProgress,
} from './progressUtils'

function run(events) {
  return events.reduce(applyProgressEvent, initialProgressState())
}

describe('parseDetectorProgress', () => {
  it('parses a detector progress debug message', () => {
    expect(parseDetectorProgress('Progress: 42.5% (17/40)')).toEqual({
      pct: 42.5,
      current: 17,
      total: 40,
    })
  })

  it('returns null for unrelated messages', () => {
    expect(parseDetectorProgress('job_started')).toBeNull()
  })

  it('returns null for undefined input', () => {
    expect(parseDetectorProgress(undefined)).toBeNull()
  })
})

describe('formatConfigLines', () => {
  it('returns an empty array when there is no config yet', () => {
    expect(formatConfigLines(null)).toEqual([])
  })

  it('formats the key fields from a job config', () => {
    const lines = formatConfigLines({
      input_path: '/data/clips/clipA.aris',
      output_dir: '/data/out',
      upstream_direction: 'left',
      distance_offset: 1.5,
      export_options: ['summary_csv', 'fc'],
      platform: { model: { weights: 'cfc_detect_yolov5s_v1.pt', device: 'cuda:0' } },
    })
    expect(lines).toEqual([
      'Input file/folder: clipA.aris',
      'Results folder: /data/out',
      'Model weights: cfc_detect_yolov5s_v1.pt',
      'Device: NVIDIA GPU (CUDA)',
      'Upstream direction: left',
      'Distance offset: 1.5 m',
      'Export options: Summary CSV, FC',
    ])
  })

  it('falls back to "same folder as input" when output_dir is unset', () => {
    const lines = formatConfigLines({ input_path: '/a/b.aris', platform: {} })
    expect(lines).toContain('Results folder: same folder as input')
  })
})

describe('formatLogEntry', () => {
  it('formats a known event', () => {
    expect(formatLogEntry({ event: 'initialized_tracker' })).toBe('Tracker ready')
  })

  it('falls back to the raw event name for unknown events', () => {
    expect(formatLogEntry({ event: 'some_new_event' })).toBe('some_new_event')
  })

  it('includes the detector version when present', () => {
    expect(formatLogEntry({ event: 'job_started', detector_version: 'v3' })).toBe(
      'Job started · detector v3'
    )
  })
})

describe('applyProgressEvent', () => {
  it('sets stage from STAGE_LABELS and logs non-debug events', () => {
    const state = run([{ event: 'initialized_tracker', level: 'info' }])
    expect(state.stage).toBe('Tracking')
    expect(state.logEntries).toHaveLength(1)
  })

  it('does not log debug-level events', () => {
    const state = run([{ event: 'initialized_tracker', level: 'debug' }])
    expect(state.logEntries).toHaveLength(0)
  })

  it('tracks detection progress as a fraction of frames once dataset/batch size are known', () => {
    const state = run([
      { event: 'initialized_dataloader', level: 'info', dataset_size: 100, batch_size: 10 },
      { event: 'Progress: 20.0% (2/10)', level: 'debug' },
    ])
    expect(state.detecting).toBe(true)
    expect(state.detectPct).toBe(20)
    expect(state.detectFrames).toEqual({ current: 20, total: 100 })
  })

  it('clamps detection frame count to the dataset size on a partial final batch', () => {
    const state = run([
      { event: 'initialized_dataloader', level: 'info', dataset_size: 95, batch_size: 10 },
      { event: 'Progress: 100.0% (10/10)', level: 'debug' },
    ])
    expect(state.detectFrames).toEqual({ current: 95, total: 95 })
  })

  it('resets the detection bar when a file completes', () => {
    const state = run([
      { event: 'initialized_dataloader', level: 'debug', dataset_size: 100, batch_size: 10 },
      { event: 'Progress: 50.0% (5/10)', level: 'debug' },
      { event: 'processed_file_stats', level: 'info', num_counts: 3 },
    ])
    expect(state.detecting).toBe(false)
    expect(state.detectPct).toBe(0)
    expect(state.detectFrames).toBeNull()
    expect(state.filesComplete).toBe(1)
    // processed_file_stats also falls through to update stage and log, same
    // event, not an early return.
    expect(state.stage).toBe('Processing')
    expect(state.logEntries).toHaveLength(1)
  })

  it('counts a file as failed only once its retries are exhausted', () => {
    const state = run([
      { event: 'safe_execution_exception', level: 'warning', function: '_run', attempt: 1 },
      { event: 'safe_execution_failed', level: 'error', function: '_run', retries: 3 },
    ])
    expect(state.filesFailed).toBe(1)
    expect(state.filesComplete).toBe(0)
  })

  it('ignores safe_execution_failed from an unrelated function', () => {
    const state = run([
      { event: 'safe_execution_failed', level: 'error', function: 'some_other_step' },
    ])
    expect(state.filesFailed).toBe(0)
  })

  it('tracks files_discovered separately from the log/stage machinery', () => {
    const state = run([{ event: 'files_discovered', num_files: 5 }])
    expect(state.filesTotal).toBe(5)
    expect(state.logEntries).toHaveLength(0)
    expect(state.stage).toBe('Connecting')
  })

  it('marks jobFinished on job_finished without altering completion status', () => {
    const state = run([{ event: 'job_finished', level: 'info', duration_sec: 12.4 }])
    expect(state.jobFinished).toBe(true)
    expect(state.completed).toBe(false)
    expect(state.stage).toBe('Finishing')
  })

  it('a completed done event sets stage/completed and stops detecting', () => {
    const state = run([
      { event: 'initialized_dataloader', level: 'info', dataset_size: 100, batch_size: 10 },
      { event: 'Progress: 50.0% (5/10)', level: 'debug' },
      { event: 'done', status: 'completed' },
    ])
    expect(state.stage).toBe('Complete')
    expect(state.completed).toBe(true)
    expect(state.detecting).toBe(false)
    expect(state.done).toBe(true)
  })

  it('a cancelled done event sets cancelled', () => {
    const state = run([{ event: 'done', status: 'cancelled' }])
    expect(state.stage).toBe('Cancelled')
    expect(state.cancelled).toBe(true)
  })

  it('a failed done event sets the error message', () => {
    const state = run([{ event: 'done', status: 'failed', error: 'pipeline exploded' }])
    expect(state.stage).toBe('Failed')
    expect(state.error).toBe('pipeline exploded')
  })

  it('a failed done event with no error falls back to a generic message', () => {
    const state = run([{ event: 'done', status: 'failed' }])
    expect(state.error).toBe('Job failed')
  })

  it('a connection-lost event only sets the error, leaving stage/completion alone', () => {
    const state = run([
      { event: 'initialized_tracker', level: 'info' },
      { event: '__connection_lost', error: 'Lost connection to server' },
    ])
    expect(state.error).toBe('Lost connection to server')
    expect(state.stage).toBe('Tracking')
    expect(state.completed).toBe(false)
    expect(state.cancelled).toBe(false)
    expect(state.done).toBe(false)
  })

  it('passes through an unknown event type without throwing', () => {
    const state = run([{ event: 'some_future_event_we_dont_know_about', level: 'info' }])
    expect(state.stage).toBe('Connecting')
    expect(state.logEntries).toHaveLength(1)
  })
})

describe('deriveFileCounts', () => {
  it('before job_finished, successes come straight from filesComplete', () => {
    const state = { ...initialProgressState(), filesComplete: 2, filesFailed: 1, filesTotal: 5, jobFinished: false }
    expect(deriveFileCounts(state)).toEqual({ filesAttempted: 3, filesSucceeded: 2 })
  })

  it('after job_finished, successes are derived from the total minus failures', () => {
    // filesComplete undercounts (a success that never logged processed_file_stats),
    // so once job_finished is true, filesTotal - filesFailed is trusted instead.
    const state = { ...initialProgressState(), filesComplete: 2, filesFailed: 1, filesTotal: 5, jobFinished: true }
    expect(deriveFileCounts(state)).toEqual({ filesAttempted: 3, filesSucceeded: 4 })
  })

  it('never returns a negative success count', () => {
    const state = { ...initialProgressState(), filesComplete: 0, filesFailed: 5, filesTotal: 2, jobFinished: true }
    expect(deriveFileCounts(state)).toEqual({ filesAttempted: 5, filesSucceeded: 0 })
  })
})
