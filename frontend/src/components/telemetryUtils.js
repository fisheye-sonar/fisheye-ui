// Mirrors fisheye_ui.enums.TelemetryChoice.
export const TELEMETRY_CHOICES = {
  OFF: 'off',
  ANONYMOUS: 'anonymous',
  CONTACT: 'contact',
}

export const EMPTY_CONTACT = { name: '', institution: '', email: '' }

// Loose client-side check so Save can stay disabled until the email looks
// plausible. The backend (pydantic EmailStr) is the real validator - a 422
// from it is still shown to the user.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function looksLikeEmail(email) {
  return EMAIL_PATTERN.test((email || '').trim())
}

// Nothing is pre-selected (choice starts null), so Save stays disabled
// until the user actively picks an option.
export function canSave(choice, contact) {
  if (!choice) return false
  if (choice === TELEMETRY_CHOICES.CONTACT) return looksLikeEmail(contact?.email)
  return true
}

// Body for PUT /settings/telemetry. Contact details are only ever included
// for the "contact" choice, and blank optional fields are sent as null
// rather than empty strings.
export function buildTelemetryRequest(choice, contact) {
  if (choice !== TELEMETRY_CHOICES.CONTACT) return { choice }
  const trimmed = value => (value || '').trim() || null
  return {
    choice,
    contact: {
      name: trimmed(contact?.name),
      institution: trimmed(contact?.institution),
      email: (contact?.email || '').trim(),
    },
  }
}

// Footer label. A null choice ("not chosen yet") is treated as off - nothing
// is sent until the user opts in.
export function telemetryChoiceLabel(choice) {
  if (choice === TELEMETRY_CHOICES.ANONYMOUS) return 'Anonymous'
  if (choice === TELEMETRY_CHOICES.CONTACT) return 'On, with contact'
  return 'Off'
}
