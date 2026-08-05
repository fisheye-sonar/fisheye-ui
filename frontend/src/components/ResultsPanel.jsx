import { useEffect, useState } from 'react'
import { buildClips, computeTotals, formatBytes, labelForFile, outputUrl, parseCsv } from './resultsUtils'

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

export default function ResultsPanel({ jobId }) {
  const [job, setJob] = useState(null)
  const [outputFiles, setOutputFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [expanded, setExpanded] = useState({})
  const [openClips, setOpenClips] = useState(() => new Set())
  const [filter, setFilter] = useState('')

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
          // Auto-expand when there's only one clip — collapsing it would just
          // add a click to reach a download that's otherwise front and center.
          const jobResults = jobData.results ?? []
          if (jobResults.length === 1) {
            setOpenClips(new Set([jobResults[0]['Source.Name']]))
          }
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

  function toggleClip(sourceName) {
    setOpenClips(prev => {
      const next = new Set(prev)
      if (next.has(sourceName)) next.delete(sourceName)
      else next.add(sourceName)
      return next
    })
  }

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
  const clips = buildClips(results, outputFiles)
  const totals = computeTotals(results)

  // Totals above always reflect every clip — only the row lists below are
  // narrowed by the filter, so the summary stays trustworthy while searching.
  const filterNeedle = filter.trim().toLowerCase()
  const filteredClips = filterNeedle
    ? clips.filter(clip => clip.sourceName?.toLowerCase().includes(filterNeedle))
    : clips

  return (
    <div className="space-y-6">
      {loading && <p className="text-sm text-gray-500">Loading results…</p>}

      {loadError && (
        <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{loadError}</p>
      )}

      {!loading && !loadError && (
        <>
          {clips.length > 1 && (
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filter results by ARIS or DDF name…"
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-400"
            />
          )}

          <div>
            <h2 className="text-sm font-medium text-gray-700 mb-3">Counts</h2>
            {results.length > 0 ? (
              <div className="max-h-96 overflow-y-auto overflow-x-auto border border-gray-200 rounded-lg">
                <table className="text-sm w-full">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium text-gray-600">File</th>
                      <th className="text-right px-3 py-2 font-medium text-gray-600">Upstream</th>
                      <th className="text-right px-3 py-2 font-medium text-gray-600">Downstream</th>
                      <th className="text-right px-3 py-2 font-medium text-gray-600">Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredClips.map(clip => (
                      <tr key={clip.sourceName} className="border-t border-gray-100">
                        <td className="px-3 py-2 text-gray-700">{clip.sourceName}</td>
                        <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.upstream}</td>
                        <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.downstream}</td>
                        <td className="px-3 py-2 text-right text-gray-700 tabular-nums">{clip.net}</td>
                      </tr>
                    ))}
                    {filteredClips.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-2 text-gray-400">No clips match “{filter}”.</td>
                      </tr>
                    )}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-gray-200 bg-gray-50 font-medium sticky bottom-0">
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
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-sm font-medium text-gray-700">Downloads</h2>
              {outputFiles.length > 1 && (
                <a
                  href={`/jobs/${jobId}/outputs/download-all`}
                  className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
                >
                  Download all
                </a>
              )}
            </div>
            <p className="text-xs text-gray-400 mb-3">
              These files are already saved to your output folder — download a copy here only if you need one elsewhere.
            </p>
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

              <div className="max-h-96 overflow-y-auto space-y-3 pr-1">
                {filteredClips.length === 0 && clips.length > 0 && (
                  <p className="text-xs text-gray-400">No clips match “{filter}”.</p>
                )}

                {filteredClips.map(clip => {
                  const isOpen = openClips.has(clip.sourceName)
                  return (
                    <div key={clip.sourceName} className="rounded-lg border border-gray-200 px-3 py-2">
                      <button
                        onClick={() => toggleClip(clip.sourceName)}
                        className="w-full flex items-center justify-between text-sm font-medium text-gray-700"
                      >
                        {clip.sourceName}
                        <svg
                          className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                          fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                      {isOpen && (
                        <div className="space-y-3 mt-2">
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
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}