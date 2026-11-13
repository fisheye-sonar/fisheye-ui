import { describe, expect, it } from 'vitest'
import {
  TELEMETRY_CHOICES,
  buildTelemetryRequest,
  canSave,
  looksLikeEmail,
  telemetryChoiceLabel,
} from './telemetryUtils'

const CONTACT = { name: ' Jane Doe ', institution: '', email: ' jane@example.edu ' }

describe('canSave', () => {
  it('is disabled until an option is picked', () => {
    expect(canSave(null, CONTACT)).toBe(false)
  })

  it('is enabled for off and anonymous without contact details', () => {
    expect(canSave(TELEMETRY_CHOICES.OFF, null)).toBe(true)
    expect(canSave(TELEMETRY_CHOICES.ANONYMOUS, null)).toBe(true)
  })

  it('requires a plausible email for contact', () => {
    expect(canSave(TELEMETRY_CHOICES.CONTACT, { email: '' })).toBe(false)
    expect(canSave(TELEMETRY_CHOICES.CONTACT, { email: 'jane' })).toBe(false)
    expect(canSave(TELEMETRY_CHOICES.CONTACT, CONTACT)).toBe(true)
  })
})

describe('looksLikeEmail', () => {
  it.each(['jane@example.edu', ' jane@example.edu '])('accepts %j', email => {
    expect(looksLikeEmail(email)).toBe(true)
  })

  it.each(['', 'jane', 'jane@', '@example.edu', 'jane@example', 'jane @example.edu'])(
    'rejects %j',
    email => {
      expect(looksLikeEmail(email)).toBe(false)
    },
  )
})

describe('buildTelemetryRequest', () => {
  it('never includes contact details for off or anonymous', () => {
    expect(buildTelemetryRequest(TELEMETRY_CHOICES.OFF, CONTACT)).toEqual({ choice: 'off' })
    expect(buildTelemetryRequest(TELEMETRY_CHOICES.ANONYMOUS, CONTACT)).toEqual({
      choice: 'anonymous',
    })
  })

  it('trims contact fields and sends blank optional ones as null', () => {
    expect(buildTelemetryRequest(TELEMETRY_CHOICES.CONTACT, CONTACT)).toEqual({
      choice: 'contact',
      contact: { name: 'Jane Doe', institution: null, email: 'jane@example.edu' },
    })
  })
})

describe('telemetryChoiceLabel', () => {
  it('treats not-chosen-yet as off', () => {
    expect(telemetryChoiceLabel(null)).toBe('Off')
  })

  it('labels each choice', () => {
    expect(telemetryChoiceLabel('off')).toBe('Off')
    expect(telemetryChoiceLabel('anonymous')).toBe('Anonymous')
    expect(telemetryChoiceLabel('contact')).toBe('On, with contact')
  })
})
