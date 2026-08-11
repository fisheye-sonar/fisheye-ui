import { useEffect, useRef, useState } from 'react'
import UpdateBanner from './UpdateBanner'
import { BATCH_SIZE_OPTIONS, MAX_WORKERS_OPTIONS, PLATFORM_PRESETS, WORKERS_OPTIONS, presetKeyFor } from './platformPresets'

// Electron always exposes a working native picker (dialog.showOpenDialog is
// the same API on every OS), so it takes priority over the backend's
// native_file_picker flag - which is false on Windows, where the backend
// has no AppleScript/zenity equivalent (see fisheye_ui/routes/platform.py).
const hasElectronPicker = typeof window !== 'undefined' && typeof window.fisheyeElectron?.pickFile === 'function'

const EXPORT_OPTIONS = [
  { value: 'summary_csv', label: 'Summary CSV' },
  { value: 'detailed_csv', label: 'Detailed CSV (per file)' },
  { value: 'fc', label: 'ARISFish Count File' },
  { value: 'mot', label: 'Multi-Object Tracking (MOT)'}
]

// Weights are downloaded automatically from GitHub releases on first run
// (and cached locally after), keyed by filename — see fisheye's
// common/weights.py. This is a static list for now rather instead of querying the
// releases API live, so it stays in sync with this repo's supported models
const MODEL_CATALOG = [
    { value: 'cfc_detect_yolov5m_v0.pt', label: 'YOLOv5m v0 — Recommended' },
    { value: 'cfc_detect_yolov5s_v1.pt', label: 'YOLOv5s - v1' },
    { value: 'cfc_detect_yolov5s_v0.pt', label: 'YOLOv5s - v0' },
]

export default function SubmitForm({ onJobCreated }) {
  const [inputPath, setInputPath] = useState('')
  // What's shown in the UI - the real path for native picks (useful to see),
  // but just the original filename for uploads (the temp path it's saved
  // under on disk is an implementation detail, not something to show the user).
  const [inputLabel, setInputLabel] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [modelWeights, setModelWeights] = useState(MODEL_CATALOG[0].value)
  const [customWeightsPath, setCustomWeightsPath] = useState('')
  const [device, setDevice] = useState('mps')
  // What /platform reported as sys.platform, normalized to
  // 'windows' | 'darwin' | 'linux' | 'other'. Only used to disambiguate the
  // cuda preset (see presetKeyFor) - not shown in the UI.
  const [detectedOs, setDetectedOs] = useState(null)
  const [platformConfig, setPlatformConfig] = useState(PLATFORM_PRESETS.mps.dataset)
  // Defaults to true so desktop's UI doesn't flash to the upload variant
  // before this resolves; a remote worker flips it to false once /platform responds.
  const [nativeFilePicker, setNativeFilePicker] = useState(true)
  // Defaults to all three so the dropdown doesn't flash disabled options
  // before this resolves; narrowed once /platform reports what torch can
  // actually see on this machine (e.g. no mps on a headless AWS GPU worker).
  const [availableDevices, setAvailableDevices] = useState(['mps', 'cuda', 'cpu'])
  // The device /platform recommended for this machine. Kept separate from
  // `device` so the "Recommended" tag stays on the right option even if the
  // user picks something else.
  const [recommendedDevice, setRecommendedDevice] = useState(null)
  const [temporaryGpuHosting, setTemporaryGpuHosting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  function handleDeviceChange(newDevice, os) {
    setDevice(newDevice)
    setPlatformConfig(PLATFORM_PRESETS[presetKeyFor(newDevice, os)].dataset)
  }

  function setPlatformField(field, value) {
    setPlatformConfig(prev => ({ ...prev, [field]: value }))
  }

  // Pre-select the best available device for this machine; the dropdown
  // stays editable in case the user wants to override it.
  useEffect(() => {
    let cancelled = false
    fetch('/platform')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (cancelled || !data) return
        if (typeof data.os === 'string') setDetectedOs(data.os)
        if (data.device) {
          handleDeviceChange(data.device, data.os)
          setRecommendedDevice(data.device)
        }
        if (typeof data.native_file_picker === 'boolean') setNativeFilePicker(hasElectronPicker || data.native_file_picker)
        if (Array.isArray(data.available_devices)) setAvailableDevices(data.available_devices)
        if (typeof data.temporary_gpu_hosting === 'boolean') setTemporaryGpuHosting(data.temporary_gpu_hosting)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const [gpuBusy, setGpuBusy] = useState(false)

  // Jobs share whatever GPU is on this machine - there's no queue, so a job
  // submitted while another is running competes for the same device instead
  // of waiting its turn. Poll while this form is up so the warning appears
  // even if the other job started after the page loaded.
  useEffect(() => {
    let cancelled = false
    const checkActive = () => {
      fetch('/jobs/active')
        .then(res => (res.ok ? res.json() : null))
        .then(data => { if (!cancelled && data) setGpuBusy(data.active) })
        .catch(() => {})
    }
    checkActive()
    const interval = setInterval(checkActive, 5000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const [upstreamDirection, setUpstreamDirection] = useState('left')
  const [distanceOffset, setDistanceOffset] = useState(0)
  const [exportOptions, setExportOptions] = useState(['summary_csv', 'detailed_csv', 'fc'])
  const [outputDir, setOutputDir] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [picking, setPicking] = useState(null)
  // Set when the backend reports the target location already has
  // predictions (409) - holds what to show in the confirmation dialog.
  const [rerunConfirm, setRerunConfirm] = useState(null)

  async function browsePath(type) {
    setPicking(type)
    try {
      if (hasElectronPicker) {
        const path = type === 'directory'
          ? await window.fisheyeElectron.pickDirectory()
          : await window.fisheyeElectron.pickFile()
        if (path) {
          setInputPath(path)
          setInputLabel(path)
        }
        return
      }
      const endpoint = type === 'directory' ? '/files/directory-selection' : '/files/file-selection'
      const res = await fetch(endpoint, { method: 'POST' })
      if (!res.ok) return
      const { path } = await res.json()
      if (path) {
        setInputPath(path)
        setInputLabel(path)
      }
    } finally {
      setPicking(null)
    }
  }

  // Counterpart to browsePath for deployments with no server-side file
  // picker (e.g. a remote GPU worker) - uploads the file's bytes instead
  // of asking the server to resolve a local path.
  async function uploadFile(file) {
    setUploading(true)
    setError(null)
    try {
      const res = await fetch(`/files/upload?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        body: file,
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? 'Upload failed')
        return
      }
      const { path } = await res.json()
      if (path) {
        setInputPath(path)
        setInputLabel(file.name)
      }
    } catch {
      setError('Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function toggleExport(value) {
    setExportOptions(prev =>
      prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value]
    )
  }

  async function submitJob(confirmRerun) {
    setError(null)
    setSubmitting(true)

    const preset = PLATFORM_PRESETS[presetKeyFor(device, detectedOs)]
    const platform = {
      ...preset,
      dataset: platformConfig,
      model: { ...preset.model, weights: customWeightsPath.trim() || modelWeights },
    }

    const body = {
      input_path: inputPath,
      upstream_direction: upstreamDirection,
      distance_offset: distanceOffset,
      export_options: exportOptions,
      platform,
      ...(outputDir && { output_dir: outputDir }),
      confirm_rerun: confirmRerun,
    }

    try {
      const res = await fetch('/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (res.status === 409) {
        const { detail } = await res.json()
        setRerunConfirm({
          existingOutputDir: detail.existing_output_dir,
          suggestedOutputDir: detail.suggested_output_dir,
        })
        return
      }
      if (!res.ok) {
        const data = await res.json()
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to start job')
      }
      const { id } = await res.json()
      setRerunConfirm(null)
      onJobCreated(id)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    if (!inputPath) {
      setError('Select an input file or folder before starting.')
      return
    }
    if (exportOptions.length === 0) {
      setError('Select at least one export option.')
      return
    }
    if (!Number.isFinite(distanceOffset)) {
      setError('Distance offset must be a number.')
      return
    }

    await submitJob(false)
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center py-12 px-4">
      <div className="w-full max-w-4xl">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
          <p className="text-gray-500 mt-1">Predict salmon counts from ARIS and/or DIDSON sonar files.</p>
        </div>

        <UpdateBanner />

        {temporaryGpuHosting && (
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-6">
            This web version uses computing resources provided by our team so you can try FishEye without any setup.
            In the full release, the web app will require you to use your own cloud provider account for processing.
            The desktop app runs locally on your computer and does not require a cloud provider account.
          </p>
        )}

        <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Input file or folder</label>
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => {
                e.preventDefault()
                setDragOver(false)
                const file = e.dataTransfer.files?.[0]
                if (!file) { console.warn('[fisheye] drop had no file in dataTransfer.files'); return }
                if (!window.fisheyeElectron) {
                  // No Electron bridge to resolve a local path (remote deployment,
                  // or the dev server opened in a plain browser) - upload the
                  // dropped file's bytes instead.
                  uploadFile(file)
                  return
                }
                try {
                  const path = window.fisheyeElectron.getPathForFile(file)
                  if (path) setInputPath(path)
                } catch (err) {
                  console.error('[fisheye] getPathForFile threw', err)
                }
              }}
              className={`border-2 border-dashed rounded-xl transition-colors ${
                dragOver
                  ? 'border-blue-400 bg-blue-50'
                  : inputPath
                    ? 'border-gray-200 bg-white'
                    : 'border-gray-200 bg-gray-50 hover:border-gray-300'
              }`}
            >
              {inputPath ? (
                <div className="flex items-center gap-3 px-4 py-3">
                  <svg className="w-5 h-5 text-blue-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="flex-1 text-sm text-gray-800 font-mono truncate min-w-0">{inputLabel}</span>
                  <button
                    type="button"
                    onClick={() => { setInputPath(''); setInputLabel('') }}
                    className="shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
                    aria-label="Clear selection"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ) : (
                <div className="py-8 px-4 text-center">
                  <svg className="mx-auto w-8 h-8 text-gray-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  <p className="text-sm text-gray-500">Drop a file{nativeFilePicker ? ' or folder' : ''} here</p>
                  <p className="text-xs text-gray-400 mt-0.5 mb-4">
                    {nativeFilePicker ? 'ARIS or DIDSON files, or a folder containing them' : 'ARIS or DIDSON files'}
                  </p>
                  <div className="flex gap-2 justify-center">
                    {nativeFilePicker ? (
                      <>
                        <button
                          type="button"
                          onClick={() => browsePath('file')}
                          disabled={!!picking}
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 disabled:opacity-50 transition-colors"
                        >
                          {picking === 'file' ? 'Opening…' : 'Select file'}
                        </button>
                        <button
                          type="button"
                          onClick={() => browsePath('directory')}
                          disabled={!!picking}
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 disabled:opacity-50 transition-colors"
                        >
                          {picking === 'directory' ? 'Opening…' : 'Select folder'}
                        </button>
                      </>
                    ) : (
                      <>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept=".aris,.ddf"
                          className="sr-only"
                          onChange={e => {
                            const file = e.target.files?.[0]
                            if (file) uploadFile(file)
                            e.target.value = ''
                          }}
                        />
                        <button
                          type="button"
                          onClick={() => fileInputRef.current?.click()}
                          disabled={uploading}
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 disabled:opacity-50 transition-colors"
                        >
                          {uploading ? 'Uploading…' : 'Upload file'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
            <input type="text" required value={inputPath} onChange={() => {}} className="sr-only" tabIndex={-1} aria-hidden="true" />
          </div>

          <div>
            <div className="flex items-center gap-1.5 mb-1">
              <label className="block text-sm font-medium text-gray-700">Model</label>
              <div className="relative group">
                <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" fill="currentColor" />
                  <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                  <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                </svg>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 bg-gray-900 text-white text-xs rounded-lg px-3 py-2.5 hidden group-hover:block z-10 space-y-1.5">
                  <p>Pretrained weights are <strong>downloaded automatically on first run</strong> from GitHub releases. An internet connection is required the first time; subsequent runs use the cached file.</p>
                  <p>
                    See release assets for available models:{' '}
                    <a
                      href="https://github.com/fisheye-sonar/fisheye/releases"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline hover:text-blue-300"
                    >
                      github.com/fisheye-sonar/fisheye/releases
                    </a>
                  </p>
                  <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                </div>
              </div>
            </div>
            <select
              value={modelWeights}
              onChange={e => setModelWeights(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {MODEL_CATALOG.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <label className="block text-sm font-medium text-gray-700">Device</label>
                <div className="relative group">
                  <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" fill="currentColor" />
                    <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                    <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                  </svg>
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2.5 hidden group-hover:block z-10 pointer-events-none space-y-1.5">
                    <p>The recommended device is selected automatically. Change it only if you want to use a different device.</p>
                    <p><strong>Apple Silicon (MPS):</strong> For newer Macs with M1, M2, M3, or M4 chips.</p>
                    <p><strong>NVIDIA GPU (CUDA):</strong> For Windows/Linux computers with an NVIDIA graphics card.</p>
                    <p><strong>CPU:</strong> Works on any computer. Choose this if you're unsure.</p>
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                  </div>
                </div>
              </div>
              <select
                value={device}
                onChange={e => handleDeviceChange(e.target.value, detectedOs)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="mps" disabled={!availableDevices.includes('mps')}>
                  MPS (Apple Silicon){recommendedDevice === 'mps' && ' — Recommended'}{!availableDevices.includes('mps') && ' — unavailable on this machine'}
                </option>
                <option value="cuda" disabled={!availableDevices.includes('cuda')}>
                  CUDA (NVIDIA GPU){recommendedDevice === 'cuda' && ' — Recommended'}{!availableDevices.includes('cuda') && ' — unavailable on this machine'}
                </option>
                <option value="cpu" disabled={!availableDevices.includes('cpu')}>
                  CPU{recommendedDevice === 'cpu' && ' — Recommended'}
                </option>
              </select>
            </div>

            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <label className="block text-sm font-medium text-gray-700">Upstream direction</label>
                <div className="relative group">
                  <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" fill="currentColor" />
                    <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                    <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                  </svg>
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 hidden group-hover:block z-10 pointer-events-none">
                    The direction fish travel when moving upstream. If upstream is <strong>Left</strong>, fish cross right→left. If upstream is <strong>Right</strong>, fish cross left→right.
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                  </div>
                </div>
              </div>
              <div className="flex rounded-lg border border-gray-300 overflow-hidden">
                {['left', 'right'].map(dir => (
                  <button
                    key={dir}
                    type="button"
                    onClick={() => setUpstreamDirection(dir)}
                    className={`flex-1 py-2 text-sm font-medium capitalize transition-colors ${
                      upstreamDirection === dir
                        ? 'bg-blue-600 text-white'
                        : 'bg-white text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {dir}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <label className="block text-sm font-medium text-gray-700">Export options</label>
              <div className="relative group">
                <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" fill="currentColor" />
                  <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                  <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                </svg>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 bg-gray-900 text-white text-xs rounded-lg px-3 py-2.5 hidden group-hover:block z-10 pointer-events-none space-y-1.5">
                  <p><strong>Summary CSV:</strong> Exports one CSV containing one row per ARIS/DIDSON file with upstream, downstream, and net counts.</p>
                  <p><strong>Detailed CSV (per file):</strong> Exports one CSV per ARIS/DIDSON file containing one row per detected fish with its distance, direction, and additional measurement data.</p>
                  <p><strong>ARISFish Count File:</strong> Exports Sound Metrics' ARISFish-compatible count files containing each detected fish's distance, direction, and additional measurement data. This is the only export format that can be opened in ARISFish to review and edit fish markers.</p>
                  <p><strong>Multi-Object Tracking (MOT):</strong> Exports fish tracks in Multi-Object Tracking (MOT) format for computer vision research and evaluation tools.</p>
                  <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                </div>
              </div>
            </div>
            <div className="flex gap-4">
              {EXPORT_OPTIONS.map(opt => (
                <label key={opt.value} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={exportOptions.includes(opt.value)}
                    onChange={() => toggleExport(opt.value)}
                    className="rounded border-gray-300 text-blue-600"
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-700 select-none">Advanced options</summary>
            <div className="mt-3 space-y-3">
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <label className="block text-sm font-medium text-gray-700">Mark offset (m)</label>
                  <div className="relative group">
                    <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" fill="currentColor" />
                      <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                      <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                    </svg>
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 hidden group-hover:block z-10 pointer-events-none">
                      Controls how far marks are placed from each detected fish in Sound Metrics' ARISFish software. Markers placed directly on the fish can make it difficult to review or measure the fish's length. A value of 0 places markers directly on the fish. If you use this setting, we recommend 1–2 meters.
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                    </div>
                  </div>
                </div>
                <input
                  type="number"
                  step="0.1"
                  value={distanceOffset}
                  onChange={e => setDistanceOffset(parseFloat(e.target.value))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              {nativeFilePicker && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Output folder (optional)</label>
                  <input
                    type="text"
                    value={outputDir}
                    onChange={e => setOutputDir(e.target.value)}
                    placeholder="Defaults to same folder as input file"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              )}
              {nativeFilePicker && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Custom model weights path (optional)</label>
                  <input
                    type="text"
                    value={customWeightsPath}
                    onChange={e => setCustomWeightsPath(e.target.value)}
                    placeholder="Overrides the selected model above"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    Use this if you've placed a weights file manually, e.g. because automatic download failed.
                  </p>
                </div>
              )}

              <div className="border-t border-gray-100 pt-3">
                <div className="flex items-center gap-1.5 mb-3">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Platform configuration</p>
                  <div className="relative group">
                    <svg className="w-5 h-5 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" fill="currentColor" />
                      <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                      <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                    </svg>
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 hidden group-hover:block z-10 pointer-events-none">
                      These settings are automatically configured to work well with the selected device. Most users won't need to change them, but advanced users can fine-tune them to trade off processing speed and performance for their specific hardware.
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Frames per batch</label>
                    <select
                      value={platformConfig.batch_size}
                      onChange={e => setPlatformField('batch_size', parseInt(e.target.value))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {BATCH_SIZE_OPTIONS.map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Max parallel workers</label>
                    <select
                      value={platformConfig.max_workers}
                      onChange={e => setPlatformField('max_workers', parseInt(e.target.value))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {MAX_WORKERS_OPTIONS.map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5 mb-1">
                      <label className="block text-sm font-medium text-gray-700">Dataloader workers</label>
                      <div className="relative group">
                        <svg className="w-4 h-4 text-amber-600 hover:text-amber-700 transition-colors cursor-help" viewBox="0 0 24 24">
                          <circle cx="12" cy="12" r="10" fill="currentColor" />
                          <path stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4" />
                          <path stroke="white" strokeWidth={1.5} strokeLinecap="round" d="M12 17h.01" />
                        </svg>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 hidden group-hover:block z-10 pointer-events-none">
                          Background processes that load data in parallel. Higher can speed things up on Linux, but on Windows this should usually stay 0 - each one is expensive to start there regardless of CPU count.
                          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                        </div>
                      </div>
                    </div>
                    <select
                      value={platformConfig.workers}
                      onChange={e => setPlatformField('workers', parseInt(e.target.value))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {WORKERS_OPTIONS.map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="flex gap-4 mt-3">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={platformConfig.use_multithreading}
                      onChange={e => setPlatformField('use_multithreading', e.target.checked)}
                      className="rounded border-gray-300 text-blue-600"
                    />
                    Use multithreading
                  </label>
                </div>
              </div>
            </div>
          </details>

          {gpuBusy && (
            <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
              Another job is currently running on this machine. The GPU is shared, so processing time may increase until it finishes.
            </p>
          )}

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {submitting ? 'Starting job…' : 'Run inference'}
          </button>
        </form>
      </div>

      {rerunConfirm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-lg max-w-md w-full p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Predictions already exist</h2>
            <div className="text-sm text-gray-600 space-y-2">
              <p>This location already has results:</p>
              <p className="font-mono text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1.5 break-all">
                {rerunConfirm.existingOutputDir}
              </p>
              <p>Rerunning will save new results to a fresh folder instead of overwriting them:</p>
              <p className="font-mono text-xs bg-blue-50 border border-blue-200 rounded px-2 py-1.5 break-all text-blue-800">
                {rerunConfirm.suggestedOutputDir}
              </p>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setRerunConfirm(null)}
                className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => submitJob(true)}
                disabled={submitting}
                className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium transition-colors"
              >
                {submitting ? 'Starting…' : 'Rerun Anyway'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}