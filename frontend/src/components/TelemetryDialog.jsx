import { useState } from 'react'
import {
  EMPTY_CONTACT,
  TELEMETRY_CHOICES,
  buildTelemetryRequest,
  canSave,
} from './telemetryUtils'

const OPTIONS = [
  {
    value: TELEMETRY_CHOICES.OFF,
    label: "Don't send anything",
  },
  {
    value: TELEMETRY_CHOICES.ANONYMOUS,
    label: 'Send anonymously',
    hint: "Summaries aren't linked to you.",
  },
  {
    value: TELEMETRY_CHOICES.CONTACT,
    label: 'Send, and the team may contact me about my results',
    hint: 'Your name and email are sent with each summary.',
  },
]

const INPUT_CLASS =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

// Opt-in usage reporting dialog. Shown automatically at first launch (when
// no choice has been saved yet) and from the footer link afterwards.
// `settings` is the current GET /settings/telemetry response; `onClose` is
// only passed when the user already has a saved choice to fall back on - at
// first launch they have to pick one (picking "Don't send anything" is one
// click), so there's no way to leave it undecided.
export default function TelemetryDialog({ settings, onSaved, onClose }) {
  // Nothing pre-selected on first launch - choice is null until the user picks.
  const [choice, setChoice] = useState(settings?.choice ?? null)
  const [contact, setContact] = useState(() => ({
    ...EMPTY_CONTACT,
    ...Object.fromEntries(
      Object.entries(settings?.contact || {}).map(([key, value]) => [key, value ?? '']),
    ),
  }))
  const [showDetails, setShowDetails] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  function setContactField(field, value) {
    setContact(prev => ({ ...prev, [field]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/settings/telemetry', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildTelemetryRequest(choice, contact)),
      })
      if (res.status === 422) {
        setError('Please check your email address.')
        return
      }
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        setError(data?.detail || "Couldn't save your choice. Please try again.")
        return
      }
      onSaved(await res.json())
    } catch {
      setError("Couldn't save your choice. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="telemetry-dialog-title"
        className="bg-white rounded-xl shadow-lg max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="telemetry-dialog-title" className="text-lg font-semibold text-gray-900">
            Help improve FishEye
          </h2>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            >
              ×
            </button>
          )}
        </div>

        <div className="text-sm text-gray-600 space-y-2">
          <p>
            Once a day, FishEye can send the FishEye team a short summary of your recent jobs:
            fish counts, app version, and how long each job took. It never includes file names,
            folder paths, or your sonar files.
          </p>
          <button
            type="button"
            onClick={() => setShowDetails(prev => !prev)}
            aria-expanded={showDetails}
            className="text-blue-600 hover:text-blue-700 font-medium"
          >
            {showDetails ? '▾' : '▸'} See exactly what's sent
          </button>
          {showDetails && (
            <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 space-y-2">
              <p>
                <span className="font-medium text-gray-700">Sent:</span> app and model version,
                operating system, whether the job ran on CPU or GPU, whether it succeeded (or the
                type of error), how long it took, the settings used, number of files, and
                up/down/net counts and fish-size stats for each file. If you choose to be
                contacted, also your name, institution, and email.
              </p>
              <p>
                <span className="font-medium text-gray-700">Never sent:</span> file names,
                folder paths, sonar data, or full error messages.
              </p>
            </div>
          )}
        </div>

        <fieldset className="space-y-3">
          <legend className="sr-only">Usage reporting</legend>
          {OPTIONS.map(option => (
            <label key={option.value} className="flex items-start gap-3 cursor-pointer">
              <input
                type="radio"
                name="telemetry-choice"
                value={option.value}
                checked={choice === option.value}
                onChange={() => setChoice(option.value)}
                className="mt-1"
              />
              <span className="text-sm">
                <span className="text-gray-900">{option.label}</span>
                {option.hint && <span className="block text-gray-500">{option.hint}</span>}
              </span>
            </label>
          ))}
        </fieldset>

        {choice === TELEMETRY_CHOICES.CONTACT && (
          <div className="space-y-3 pl-7">
            <label className="block text-sm">
              <span className="text-gray-700">Name <span className="text-gray-400">(optional)</span></span>
              <input
                type="text"
                autoComplete="name"
                value={contact.name}
                onChange={e => setContactField('name', e.target.value)}
                className={`${INPUT_CLASS} mt-1`}
              />
            </label>
            <label className="block text-sm">
              <span className="text-gray-700">Institution <span className="text-gray-400">(optional)</span></span>
              <input
                type="text"
                autoComplete="organization"
                value={contact.institution}
                onChange={e => setContactField('institution', e.target.value)}
                className={`${INPUT_CLASS} mt-1`}
              />
            </label>
            <label className="block text-sm">
              <span className="text-gray-700">Email</span>
              <input
                type="email"
                autoComplete="email"
                required
                value={contact.email}
                onChange={e => setContactField('email', e.target.value)}
                className={`${INPUT_CLASS} mt-1`}
              />
            </label>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center justify-between gap-4 pt-2">
          <p className="text-xs text-gray-500">
            You can change this anytime from the link at the bottom of the page.
          </p>
          <div className="flex gap-3 shrink-0">
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave(choice, contact) || saving}
              className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium transition-colors"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
