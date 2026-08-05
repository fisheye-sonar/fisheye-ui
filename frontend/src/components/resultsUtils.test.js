import { describe, expect, it } from 'vitest'
import {
  buildClips,
  computeTotals,
  fileStem,
  formatBytes,
  labelForFile,
  outputUrl,
  parseCsv,
} from './resultsUtils'

describe('fileStem', () => {
  it('strips the extension', () => {
    expect(fileStem('clipA.aris')).toBe('clipA')
  })

  it('leaves names with no extension alone', () => {
    expect(fileStem('clipA')).toBe('clipA')
  })
})

describe('outputUrl', () => {
  it('builds a download URL for a top-level file', () => {
    expect(outputUrl('job-1', 'summary.csv')).toBe('/jobs/job-1/outputs/summary.csv')
  })

  it('encodes each path segment separately so slashes survive', () => {
    expect(outputUrl('job-1', 'clip A/detail file.csv')).toBe(
      '/jobs/job-1/outputs/clip%20A/detail%20file.csv'
    )
  })
})

describe('formatBytes', () => {
  it('renders sub-1KB sizes as bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
  })

  it('renders KB for sizes at or above 1024 bytes', () => {
    expect(formatBytes(2048)).toBe('2.0 KB')
  })

  it('renders MB once it crosses the next unit boundary', () => {
    expect(formatBytes(1024 * 1024 * 3)).toBe('3.0 MB')
  })

  it('caps at GB rather than continuing past the units list', () => {
    expect(formatBytes(1024 ** 4)).toBe('1024.0 GB')
  })
})

describe('labelForFile', () => {
  it('labels summary CSVs', () => {
    expect(labelForFile('clipA_job-1_summary.csv')).toBe('Summary CSV')
  })

  it('labels other CSVs as detailed', () => {
    expect(labelForFile('clipA.csv')).toBe('Detailed CSV')
  })

  it('labels FC files', () => {
    expect(labelForFile('FCe_clipA_ID_.txt')).toBe('FC file')
  })

  it('labels other txt files as MOT', () => {
    expect(labelForFile('clipA.txt')).toBe('MOT file')
  })

  it('falls back to the raw filename for unknown types', () => {
    expect(labelForFile('clipA.aris')).toBe('clipA.aris')
  })

  it('bases the label on the last path segment', () => {
    expect(labelForFile('nested/clipA_job-1_summary.csv')).toBe('Summary CSV')
  })
})

describe('parseCsv', () => {
  it('parses a simple CSV into headers and rows', () => {
    const result = parseCsv('a,b\n1,2\n3,4\n')
    expect(result).toEqual({ headers: ['a', 'b'], rows: [['1', '2'], ['3', '4']] })
  })

  it('handles quoted fields containing commas', () => {
    const result = parseCsv('a,b\n"1,2",3\n')
    expect(result).toEqual({ headers: ['a', 'b'], rows: [['1,2', '3']] })
  })

  it('handles quoted fields containing embedded newlines', () => {
    const result = parseCsv('a,b\n"line1\nline2",3\n')
    expect(result).toEqual({ headers: ['a', 'b'], rows: [['line1\nline2', '3']] })
  })

  it('unescapes doubled quotes inside a quoted field', () => {
    const result = parseCsv('a\n"say ""hi"""\n')
    expect(result).toEqual({ headers: ['a'], rows: [['say "hi"']] })
  })

  it('handles a trailing row with no final newline', () => {
    const result = parseCsv('a,b\n1,2')
    expect(result).toEqual({ headers: ['a', 'b'], rows: [['1', '2']] })
  })

  it('drops hidden columns from both headers and rows', () => {
    const result = parseCsv('a,beam_width_data,b\n1,junk,2\n')
    expect(result).toEqual({ headers: ['a', 'b'], rows: [['1', '2']] })
  })

  it('returns empty headers/rows for empty input', () => {
    expect(parseCsv('')).toEqual({ headers: [], rows: [] })
  })
})

describe('buildClips', () => {
  const outputFiles = [
    { filename: 'clipA_job-1_summary.csv' },
    { filename: '_clipA.csv' },
    { filename: 'FCe_clipA_ID_.txt' },
    { filename: 'clipA.txt' },
    { filename: '_clipB.csv' },
    { filename: 'clipA.aris' }, // raw recording alongside outputs, not an output itself
  ]
  const results = [
    { 'Source.Name': 'clipB.aris', absolute_up: '1', absolute_down: '0', net_count: '1' },
    { 'Source.Name': 'clipA.aris', absolute_up: '3', absolute_down: '1', net_count: '2' },
  ]

  it('groups each clip with only its own matching output files', () => {
    const clips = buildClips(results, outputFiles)
    const clipA = clips.find(c => c.sourceName === 'clipA.aris')
    const filenames = clipA.files.map(f => f.filename).sort()
    expect(filenames).toEqual(['FCe_clipA_ID_.txt', '_clipA.csv', 'clipA.txt'].sort())
  })

  it('does not pull in another clip file whose stem is a substring match', () => {
    const clips = buildClips(results, outputFiles)
    const clipB = clips.find(c => c.sourceName === 'clipB.aris')
    expect(clipB.files.map(f => f.filename)).toEqual(['_clipB.csv'])
  })

  it('sorts clips by source name', () => {
    const clips = buildClips(results, outputFiles)
    expect(clips.map(c => c.sourceName)).toEqual(['clipA.aris', 'clipB.aris'])
  })

  it('carries the count fields through unchanged', () => {
    const clips = buildClips(results, [])
    const clipA = clips.find(c => c.sourceName === 'clipA.aris')
    expect(clipA).toMatchObject({ upstream: '3', downstream: '1', net: '2' })
  })
})

describe('computeTotals', () => {
  it('sums counts across all clips', () => {
    const results = [
      { absolute_up: '3', absolute_down: '1', net_count: '2' },
      { absolute_up: '1', absolute_down: '0', net_count: '1' },
    ]
    expect(computeTotals(results)).toEqual({ upstream: 4, downstream: 1, net: 3 })
  })

  it('treats missing fields as zero', () => {
    expect(computeTotals([{}])).toEqual({ upstream: 0, downstream: 0, net: 0 })
  })

  it('returns zeros for no results', () => {
    expect(computeTotals([])).toEqual({ upstream: 0, downstream: 0, net: 0 })
  })
})
