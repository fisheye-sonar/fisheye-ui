import { useState } from 'react'

const PLATFORM_PRESETS = {
  mps: {
    dataset: { batch_size: 16, workers: 0, use_multithreading: true, max_workers: 2, use_blur: true },
    model: { type: 'yolov5', device: 'mps' },
    inference: { use_multithreading: true, max_workers: 2, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cuda: {
    dataset: { batch_size: 16, workers: 4, use_multithreading: true, max_workers: 4, use_blur: true },
    model: { type: 'yolov5', device: 'cuda' },
    inference: { use_multithreading: true, max_workers: 4, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cpu: {
    dataset: { batch_size: 8, workers: 0, use_multithreading: false, max_workers: 1, use_blur: true },
    model: { type: 'yolov5', device: 'cpu' },
    inference: { use_multithreading: false, max_workers: 1, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
}

const EXPORT_OPTIONS = [
  { value: 'summary_csv', label: 'Summary CSV' },
  { value: 'detailed_csv', label: 'Detailed CSV' },
  { value: 'fc', label: 'FishCount export' },
]

export default function SubmitForm({ onJobCreated }) {
  const [inputPath, setInputPath] = useState('')
  const [weightsPath, setWeightsPath] = useState('')
  const [device, setDevice] = useState('mps')
  const [upstreamDirection, setUpstreamDirection] = useState('left')
  const [distanceOffset, setDistanceOffset] = useState(0)
  const [exportOptions, setExportOptions] = useState(['summary_csv', 'detailed_csv', 'fc'])
  const [outputDir, setOutputDir] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

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
      model: { ...PLATFORM_PRESETS[device].model, weights: weightsPath },
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
      <div className="w-full max-w-xl">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">FishEye</h1>
          <p className="text-gray-500 mt-1">Run fish passage inference on an ARIS sonar file.</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">ARIS file path</label>
            <input
              type="text"
              required
              value={inputPath}
              onChange={e => setInputPath(e.target.value)}
              placeholder="/path/to/file.aris"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Model weights path</label>
            <input
              type="text"
              required
              value={weightsPath}
              onChange={e => setWeightsPath(e.target.value)}
              placeholder="/path/to/cfc_detect_yolov5s_v1.pt"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Device</label>
              <select
                value={device}
                onChange={e => setDevice(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="mps">MPS (Apple Silicon)</option>
                <option value="cuda">CUDA (NVIDIA GPU)</option>
                <option value="cpu">CPU</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Upstream direction</label>
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