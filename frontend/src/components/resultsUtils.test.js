import { describe, it, expect } from 'vitest'
import { parseCsv, buildClips } from './resultsUtils'

describe('parseCsv', () => {
  it('parses a plain CSV into headers and rows', () => {
    const { headers, rows } = parseCsv('a,b,c\n1,2,3\n4,5,6\n')
    expect(headers).toEqual(['a', 'b', 'c'])
    expect(rows).toEqual([
      ['1', '2', '3'],
      ['4', '5', '6'],
    ])
  })

  it('handles quoted fields containing commas', () => {
    const { headers, rows } = parseCsv('name,note\nfoo,"a, b, c"\n')
    expect(headers).toEqual(['name', 'note'])
    expect(rows).toEqual([['foo', 'a, b, c']])
  })

  it('handles escaped double quotes inside quoted fields', () => {
    const { rows } = parseCsv('name,note\nfoo,"she said ""hi"""\n')
    expect(rows).toEqual([['foo', 'she said "hi"']])
  })

  it('handles embedded newlines inside quoted fields without breaking rows', () => {
    const csv = 'name,blob\nfoo,"line1\nline2\nline3"\nbar,plain\n'
    const { headers, rows } = parseCsv(csv)
    expect(headers).toEqual(['name', 'blob'])
    expect(rows).toEqual([
      ['foo', 'line1\nline2\nline3'],
      ['bar', 'plain'],
    ])
  })

  it('strips carriage returns from line endings', () => {
    const { headers, rows } = parseCsv('a,b\r\n1,2\r\n')
    expect(headers).toEqual(['a', 'b'])
    expect(rows).toEqual([['1', '2']])
  })

  it('hides the beam_width_data column but keeps other columns', () => {
    const csv = 'name,beam_width_data,net_count\nfoo,"[[1,2],[3,4]]",5\n'
    const { headers, rows } = parseCsv(csv)
    expect(headers).toEqual(['name', 'net_count'])
    expect(rows).toEqual([['foo', '5']])
  })

  it('returns empty headers and rows for empty input', () => {
    expect(parseCsv('')).toEqual({ headers: [], rows: [] })
  })

  it('handles a final row with no trailing newline', () => {
    const { headers, rows } = parseCsv('a,b\n1,2')
    expect(headers).toEqual(['a', 'b'])
    expect(rows).toEqual([['1', '2']])
  })
})

describe('buildClips', () => {
  const outputFiles = [
    { filename: 'clipA_summary.csv' },
    { filename: 'detail_clipA.csv' },
    { filename: 'FCe_clipA_ID_.txt' },
    { filename: 'detail_clipAB.csv' },
    { filename: 'FCe_clipAB_ID_.txt' },
    { filename: 'clipA.aris' },
  ]

  it('matches each clip to only its own detail CSV and FC file', () => {
    const results = [{ 'Source.Name': 'clipA.mp4', absolute_up: 3, absolute_down: 1, net_count: 2 }]
    const [clip] = buildClips(results, outputFiles)

    expect(clip.sourceName).toBe('clipA.mp4')
    expect(clip.upstream).toBe(3)
    expect(clip.downstream).toBe(1)
    expect(clip.net).toBe(2)
    expect(clip.files.map(f => f.filename).sort()).toEqual([
      'FCe_clipA_ID_.txt',
      'detail_clipA.csv',
    ])
  })

  it('does not pull in another clip whose stem is a superstring match', () => {
    const results = [{ 'Source.Name': 'clipA.mp4' }]
    const [clip] = buildClips(results, outputFiles)
    const names = clip.files.map(f => f.filename)
    expect(names).not.toContain('detail_clipAB.csv')
    expect(names).not.toContain('FCe_clipAB_ID_.txt')
  })

  it('does not treat the original recording file as an output', () => {
    const results = [{ 'Source.Name': 'clipA.mp4' }]
    const [clip] = buildClips(results, outputFiles)
    expect(clip.files.map(f => f.filename)).not.toContain('clipA.aris')
  })

  it('returns no files when the source name has no matching outputs', () => {
    const results = [{ 'Source.Name': 'missing.mp4' }]
    const [clip] = buildClips(results, outputFiles)
    expect(clip.files).toEqual([])
  })

  it('returns no files when the source name is missing', () => {
    const results = [{ absolute_up: 1 }]
    const [clip] = buildClips(results, outputFiles)
    expect(clip.sourceName).toBeUndefined()
    expect(clip.files).toEqual([])
  })
})
