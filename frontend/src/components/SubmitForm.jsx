import { useEffect, useRef, useState } from 'react'

const PLATFORM_PRESETS = {
  mps: {
    dataset: { batch_size: 16, workers: 0, use_multithreading: true, max_workers: 2, use_blur: true },
    model: { type: 'yolov5', device: 'mps' },
    inference: { use_multithreading: true, max_workers: 2, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cuda: {
    dataset: { batch_size: 32, workers: 10, use_multithreading: false, max_workers: 4, use_blur: true },
    model: { type: 'yolov5', device: 'cuda:0' },
    inference: { use_multithreading: false, max_workers: 4, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cpu: {
    dataset: { batch_size: 1, workers: 0, use_multithreading: false, max_workers: 1, use_blur: true },
    model: { type: 'yolov5', device: 'cpu' },
    inference: { use_multithreading: false, max_workers: 1, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
}

const EXPORT_OPTIONS = [
  { value: 'summary_csv', label: 'Summary CSV' },
  { value: 'detailed_csv', label: 'Detailed CSV' },
  { value: 'fc', label: 'FC' },
  { value: 'mot', label: 'MOT'}
]

// Weights are downloaded automatically from GitHub releases on first run
// (and cached locally after), keyed by filename — see fisheye's
// common/weights.py. This is a static list for now rather instead of querying the
// releases API live, so it stays in sync with this repo's supported models
// only as far as we remember to update it
const MODEL_CATALOG = [
  { value: 'cfc_detect_yolov5s_v1.pt', label: 'Detector v1 (YOLOv5s)' },
    { value: 'cfc_detect_yolov5s_v0.pt', label: 'Detector v0 (YOLOv5s)' },
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
  const [platformConfig, setPlatformConfig] = useState(PLATFORM_PRESETS.mps.dataset)
  // Defaults to true so desktop's UI doesn't flash to the upload variant
  // before this resolves; a remote worker flips it to false once /platform responds.
  const [nativeFilePicker, setNativeFilePicker] = useState(true)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  function handleDeviceChange(newDevice) {
    setDevice(newDevice)
    setPlatformConfig(PLATFORM_PRESETS[newDevice].dataset)
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
        if (data.device) handleDeviceChange(data.device)
        if (typeof data.native_file_picker === 'boolean') setNativeFilePicker(data.native_file_picker)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const [upstreamDirection, setUpstreamDirection] = useState('left')
  const [distanceOffset, setDistanceOffset] = useState(0)
  const [exportOptions, setExportOptions] = useState(['summary_csv', 'detailed_csv', 'fc'])
  const [outputDir, setOutputDir] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [picking, setPicking] = useState(null)

  async function browsePath(type) {
    setPicking(type)
    try {
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

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    const platform = {
      ...PLATFORM_PRESETS[device],
      dataset: platformConfig,
      model: { ...PLATFORM_PRESETS[device].model, weights: customWeightsPath.trim() || modelWeights },
    }

    const body = {
      input_path: inputPath,
      upstream_direction: upstreamDirection,
      distance_offset: distanceOffset,
      export_options: exportOptions,
      platform,
      ...(outputDir && { output_dir: outputDir }),
    }

    try {
      const res = await fetch('/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail ?? 'Failed to start job')
      }
      const { id } = await res.json()
      onJobCreated(id)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center py-12 px-4">
      <div className="w-full max-w-4xl">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
          <p className="text-gray-500 mt-1">Predict salmon counts from ARIS and/or DIDSON sonar files.</p>
        </div>

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
                    {nativeFilePicker ? 'ARIS or DDF files, or a folder containing them' : 'ARIS or DDF files'}
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
                <svg className="w-3.5 h-3.5 text-gray-400 cursor-help" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
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
                  <svg className="w-3.5 h-3.5 text-gray-400 cursor-help" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2.5 hidden group-hover:block z-10 pointer-events-none space-y-1.5">
                    <p>Choose the device to run inference on.</p>
                    <p><strong>Apple Silicon (MPS):</strong> For newer Macs with M1, M2, M3, or M4 chips.</p>
                    <p><strong>NVIDIA GPU (CUDA):</strong> For Windows/Linux computers with an NVIDIA graphics card.</p>
                    <p><strong>CPU:</strong> Works on any computer. Choose this if you're unsure.</p>
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                  </div>
                </div>
              </div>
              <select
                value={device}
                onChange={e => handleDeviceChange(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="mps">MPS (Apple Silicon)</option>
                <option value="cuda">CUDA (NVIDIA GPU)</option>
                <option value="cpu">CPU</option>
              </select>
            </div>

            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <label className="block text-sm font-medium text-gray-700">Upstream direction</label>
                <div className="relative group">
                  <svg className="w-3.5 h-3.5 text-gray-400 cursor-help" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
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
            <label className="block text-sm font-medium text-gray-700 mb-2">Export options</label>
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
                <label className="block text-sm font-medium text-gray-700 mb-1">Distance offset (m)</label>
                <input
                  type="number"
                  step="0.1"
                  value={distanceOffset}
                  onChange={e => setDistanceOffset(parseFloat(e.target.value))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Output directory (optional)</label>
                <input
                  type="text"
                  value={outputDir}
                  onChange={e => setOutputDir(e.target.value)}
                  placeholder="Defaults to same folder as input file"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
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

              <div className="border-t border-gray-100 pt-3">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Platform configuration</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Frames per batch</label>
                    <input
                      type="number"
                      min="1"
                      value={platformConfig.batch_size}
                      onChange={e => setPlatformField('batch_size', parseInt(e.target.value))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Max parallel workers</label>
                    <input
                      type="number"
                      min="1"
                      value={platformConfig.max_workers}
                      onChange={e => setPlatformField('max_workers', parseInt(e.target.value))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
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
    </div>
  )
}