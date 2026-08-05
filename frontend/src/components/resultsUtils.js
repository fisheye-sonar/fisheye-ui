export function fileStem(name) {
  return name.replace(/\.[^/.]+$/, '')
}

// file.filename is a path relative to output_dir and may contain "/" for
// nested clips — encode each segment separately so the slash survives as a
// path separator rather than being escaped to %2F.
export function outputUrl(jobId, filename) {
  return `/jobs/${jobId}/outputs/${filename.split('/').map(encodeURIComponent).join('/')}`
}

export function formatBytes(bytes) {
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

export function labelForFile(filename) {
  const base = filename.split('/').pop()
  if (base.endsWith('_summary.csv')) return 'Summary CSV'
  if (base.endsWith('.csv')) return 'Detailed CSV'
  if (base.startsWith('FCe_') && base.endsWith('_ID_.txt')) return 'FC file'
  if (base.endsWith('.txt')) return 'MOT file'
  return filename
}

// Columns that are technical/internal and just crowd the table for a
// non-technical viewer — hidden from the preview, still present in the
// downloaded file.
export const HIDDEN_CSV_COLUMNS = ['beam_width_data']

// Single-pass scanner rather than a split-on-newline parser: some columns
// (e.g. beam_width_data) embed a serialized DataFrame with its own newlines
// inside a quoted field, which a line-first split would break mid-record.
export function parseCsv(text) {
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

// Groups output files under each clip (row of `results`) using the backend's
// exact naming patterns rather than a loose substring check: `_${stem}.csv`
// for the detailed CSV, `FCe_${stem}_ID_.txt` for the FC file, and a bare
// `${stem}.txt` for the MOT tracks file (both matched as suffixes since
// outputs list now returns paths relative to output_dir, which may carry a
// subdirectory prefix for clips nested under the batch root). A loose
// `.includes(stem)` could both pull in another clip's files (if one stem is
// a substring of another clip's filename) and pick up the original
// .aris/.ddf recording, which sits alongside the outputs but isn't one itself.
export function buildClips(results, outputFiles) {
  return results
    .map(row => {
      const sourceName = row['Source.Name']
      const stem = sourceName ? fileStem(sourceName) : null
      const files = stem
        ? outputFiles
            .filter(f =>
              f.filename.endsWith(`_${stem}.csv`) ||
              f.filename.endsWith(`FCe_${stem}_ID_.txt`) ||
              f.filename.split('/').pop() === `${stem}.txt`
            )
            // Sort by the label shown on screen (Detailed CSV / FC file / MOT
            // file), not the raw filename — the filenames don't share a
            // prefix pattern, so a filename sort wouldn't look alphabetical
            // to someone reading the rendered list.
            .sort((a, b) => labelForFile(a.filename).localeCompare(labelForFile(b.filename)))
        : []
      return {
        sourceName,
        upstream: row['absolute_up'],
        downstream: row['absolute_down'],
        net: row['net_count'],
        files,
      }
    })
    .sort((a, b) => (a.sourceName ?? '').localeCompare(b.sourceName ?? ''))
}

export function computeTotals(results) {
  return results.reduce(
    (acc, row) => ({
      upstream: acc.upstream + Number(row['absolute_up'] ?? 0),
      downstream: acc.downstream + Number(row['absolute_down'] ?? 0),
      net: acc.net + Number(row['net_count'] ?? 0),
    }),
    { upstream: 0, downstream: 0, net: 0 }
  )
}
