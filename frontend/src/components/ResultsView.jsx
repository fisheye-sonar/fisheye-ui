import { useEffect, useState } from 'react'

function fileStem(name) {
  return name.replace(/\.[^/.]+$/, '')
}

// file.filename is a path relative to output_dir and may contain "/" for
// nested clips — encode each segment separately so the slash survives as a
// path separator rather than being escaped to %2F.
function outputUrl(jobId, filename) {
  return `/jobs/${jobId}/outputs/${filename.split('/').map(encodeURIComponent).join('/')}`
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes
  let unit = -1
  do {
    value /= 1024
    unit += 1
  } while (value >= 1024 && unit < units.length - 1)
  return `${value.toFixed(1)} ${units[unit]}`
}

function labelForFile(filename) {
  if (filename.endsWith('_summary.csv')) return 'Summary CSV'
  if (filename.endsWith('.csv')) return 'Detailed CSV'
  if (filename.endsWith('.txt')) return 'FC file'
  return filename
}

// Columns that are technical/internal and just crowd the table for a
// non-technical viewer — hidden from the preview, still present in the
// downloaded file.
const HIDDEN_CSV_COLUMNS = ['beam_width_data']

// Single-pass scanner rather than a split-on-newline parser: some columns
// (e.g. beam_width_data) embed a serialized DataFrame with its own newlines
// inside a quoted field, which a line-first split would break mid-record.
function parseCsv(text) {
  const rows = []
  let row = []
  let cur = ''
  let inQuotes = false

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cur += '"'; i++ } else inQuotes = false
      } else {
        cur += ch
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      row.push(cur)
      cur = ''
    } else if (ch === '\r') {
      // skip — paired \n below ends the row
    } else if (ch === '\n') {
      row.push(cur)
      cur = ''
      rows.push(row)
      row = []
    } else {
      cur += ch
    }
  }
  if (cur !== '' || row.length > 0) {
    row.push(cur)
    rows.push(row)
  }

  if (rows.length === 0) return { headers: [], rows: [] }
  const [headers, ...dataRows] = rows

  const keep = headers.map((h, i) => (HIDDEN_CSV_COLUMNS.includes(h) ? -1 : i)).filter(i => i !== -1)
  return {
    headers: keep.map(i => headers[i]),
    rows: dataRows.map(row => keep.map(i => row[i])),
  }
}

function FilePreview({ filename, data }) {
  if (data === 'loading') return <p className="text-xs text-gray-400 mt-2 px-1">Loading…</p>
  if (data === 'error') return <p className="text-xs text-red-500 mt-2 px-1">Could not load file.</p>

  if (!filename.endsWith('.csv')) {
    return (
      <pre className="mt-2 overflow-auto max-h-72 border border-gray-200 rounded-lg bg-gray-50 p-3 text-xs text-gray-700 whitespace-pre">
        {data}
      </pre>
    )
  }

  const { headers, rows } = parseCsv(data)
  return (
    <div className="mt-2 overflow-x-auto border border-gray-200 rounded-lg">
      <table className="text-xs w-full">
        <thead className="bg-gray-50">
          <tr>
            {headers.map(h => (
              <th key={h} className="text-left px-2 py-1.5 font-medium text-gray-600 whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-gray-100">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1.5 text-gray-700 whitespace-nowrap">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OutputFileRow({ jobId, file, expandedData, onToggleView }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-gray-700">{labelForFile(file.filename)}</div>
          <div className="text-xs text-gray-400">{formatBytes(file.size_bytes)}</div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onToggleView(file.filename)}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
          >
            {expandedData ? 'Hide' : 'View'}
          </button>
          <a
            href={outputUrl(jobId, file.filename)}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
          >
            Download
          </a>
        </div>
      </div>
      {expandedData && <FilePreview filename={file.filename} data={expandedData} />}
    </div>
  )
}

export default function ResultsView({ jobId, stats, onBack }) {
  const [job, setJob] = useState(null)
  const [outputFiles, setOutputFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [expanded, setExpanded] = useState({})

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [jobRes, outputsRes] = await Promise.all([
          fetch(`/jobs/${jobId}`),
          fetch(`/jobs/${jobId}/outputs`),
        ])
        if (!jobRes.ok || !outputsRes.ok) throw new Error('request failed')
        const jobData = await jobRes.json()
        const outputsData = await outputsRes.json()
        if (!cancelled) {
          setJob(jobData)
          setOutputFiles(outputsData.files ?? [])
        }
      } catch {
        if (!cancelled) setLoadError('Could not load results for this job.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [jobId])

  async function toggleView(filename) {
    if (expanded[filename]) {
      setExpanded(prev => {
        const next = { ...prev }
        delete next[filename]
        return next
      })
      return
    }

    setExpanded(prev => ({ ...prev, [filename]: 'loading' }))
    try {
      const res = await fetch(outputUrl(jobId, filename))
      if (!res.ok) throw new Error('request failed')
      const text = await res.text()
      setExpanded(prev => ({ ...prev, [filename]: text }))
    } catch {
      setExpanded(prev => ({ ...prev, [filename]: 'error' }))
    }
  }

  const summaryFile = outputFiles.find(f => f.filename.endsWith('_summary.csv'))
  const results = job?.results ?? []
  const clips = results.map(row => {
    const sourceName = row['Source.Name']
    const stem = sourceName ? fileStem(sourceName) : null
    // Match the backend's exact naming patterns rather than a loose substring
    // check: `_${stem}.csv` for the detailed CSV, `FCe_${stem}_ID_.txt` for
    // the FC file (both matched as suffixes since outputs list now returns
    // paths relative to output_dir, which may carry a subdirectory prefix
    // for clips nested under the batch root). A loose `.includes(stem)`
    // could both pull in another clip's files (if one stem is a substring
    // of another clip's filename) and pick up the original .aris/.ddf
    // recording, which sits alongside the outputs but isn't one itself.
    const files = stem
      ? outputFiles.filter(f =>
          f.filename.endsWith(`_${stem}.csv`) || f.filename.endsWith(`FCe_${stem}_ID_.txt`)
        )
      : []
    return {
      sourceName,
      upstream: row['absolute_up'],
      downstream: row['absolute_down'],
      net: row['net_count'],
      files,
    }
  })

  const totals = results.reduce(
    (acc, row) => ({
      upstream: acc.upstream + Number(row['absolute_up'] ?? 0),
      downstream: acc.downstream + Number(row['absolute_down'] ?? 0),
      net: acc.net + Number(row['net_count'] ?? 0),
    }),
    { upstream: 0, downstream: 0, net: 0 }
  )

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center py-12 px-4">
      <div className="w-full max-w-2xl">
        <div className="mb-8 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
            <p className="text-gray-500 mt-1">
              {stats && stats.filesTotal > 0
                ? `${stats.filesSucceeded} of ${stats.filesTotal} files processed successfully.`
                : 'Job results.'}
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

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-6">
          {loading && <p className="text-sm text-gray-500">Loading results…</p>}

          {loadError && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{loadError}</p>
          )}

          {!loading && !loadError && (
            <>
              <div>
                <h2 className="text-sm font-medium text-gray-700 mb-3">Counts</h2>
                {results.length > 0 ? (
                  <div className="overflow-x-auto border border-gray-200 rounded-lg">
                    <table className="text-sm w-full">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="text-left px-3 py-2 font-medium text-gray-600">File</th>
                          <th className="text-right px-3 py-2 font-medium text-gray-600">Upstream</th>
                          <th className="text-right px-3 py-2 font-medium text-gray-600">Downstream</th>
                          <th className="text-right px-3 py-2 font-medium text-gray-600">Net</th>
                        </tr>
                      </thead>
                      <tbody>
                        {clips.map(clip => (
                          <tr key={clip.sourceName} className="border-t border-gray-100">
                            <td className="px-3 py-2 text-gray-700">{clip.sourceName}</td>
                            <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.upstream}</td>
                            <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.downstream}</td>
                            <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.net}</td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr className="border-t border-gray-200 bg-gray-50 font-medium">
                          <td className="px-3 py-2 text-gray-700">Total</td>
                          <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{totals.upstream}</td>
                          <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{totals.downstream}</td>
                          <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{totals.net}</td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No count summary is available for this run.</p>
                )}
              </div>

              <div>
                <h2 className="text-sm font-medium text-gray-700 mb-3">Downloads</h2>
                <div className="space-y-3">
                  {summaryFile && (
                    <div className="rounded-lg border border-gray-200 px-3 py-2">
                      <OutputFileRow
                        jobId={jobId}
                        file={summaryFile}
                        expandedData={expanded[summaryFile.filename]}
                        onToggleView={toggleView}
                      />
                    </div>
                  )}

                  {clips.map(clip => (
                    <div key={clip.sourceName} className="rounded-lg border border-gray-200 px-3 py-2">
                      <div className="text-sm font-medium text-gray-700 mb-2">{clip.sourceName}</div>
                      <div className="space-y-3">
                        {clip.files.map(f => (
                          <OutputFileRow
                            key={f.filename}
                            jobId={jobId}
                            file={f}
                            expandedData={expanded[f.filename]}
                            onToggleView={toggleView}
                          />
                        ))}
                        {clip.files.length === 0 && (
                          <p className="text-xs text-gray-400">No output files found for this clip.</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          <div className="flex justify-end pt-1">
            <button
              onClick={onBack}
              className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            >
              Start new job
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}