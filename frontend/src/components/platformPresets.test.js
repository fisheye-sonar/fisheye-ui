import { describe, expect, it } from 'vitest'
import { presetKeyFor } from './platformPresets'

describe('presetKeyFor', () => {
  it('routes cuda on Windows to the spawn-safe preset', () => {
    expect(presetKeyFor('cuda', 'windows')).toBe('cuda_windows')
  })

  it('routes cuda on Linux to the fork-friendly preset', () => {
    expect(presetKeyFor('cuda', 'linux')).toBe('cuda_linux')
  })

  it('is unaffected by os for cpu, the one non-cuda device realistically seen on multiple OSes', () => {
    expect(presetKeyFor('cpu', 'windows')).toBe('cpu')
    expect(presetKeyFor('cpu', 'linux')).toBe('cpu')
  })

  it('passes mps through unchanged (only reachable on darwin)', () => {
    expect(presetKeyFor('mps', 'darwin')).toBe('mps')
  })

  it('falls back to the linux-shaped preset when os is unknown', () => {
    expect(presetKeyFor('cuda', null)).toBe('cuda_linux')
  })
})