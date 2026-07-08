function fileStem(name) {
  return name.replace(/\.[^/.]+$/, '')
}

// Columns that are technical/internal and just crowd the table for a
// non-technical viewer — hidden from the preview, still present in the
// downloaded file.
const HIDDEN_CSV_COLUMNS = ['beam_width_data']

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

// file.filename is relative to output_dir and may carry a subdirectory
// prefix for clips nested under a batch root — matched as suffixes rather
// than a loose `.includes(stem)` check, which could both pull in another
// clip's files (if one stem is a substring of another clip's filename) and
// pick up the original .aris/.ddf recording that isn't an output itself.
export function buildClips(results, outputFiles) {
  return results.map(row => {
    const sourceName = row['Source.Name']
    const stem = sourceName ? fileStem(sourceName) : null
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
}
