export const PLATFORM_PRESETS = {
  mps: {
    dataset: { batch_size: 16, workers: 0, use_multithreading: true, max_workers: 2, use_blur: true },
    model: { type: 'yolov5', device: 'mps' },
    inference: { use_multithreading: true, max_workers: 2, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cuda_linux: {
    dataset: { batch_size: 32, workers: 10, use_multithreading: false, max_workers: 4, use_blur: true },
    model: { type: 'yolov5', device: 'cuda:0' },
    inference: { use_multithreading: false, max_workers: 4, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  // Windows has no fork(), only spawn - multiprocess dataloader workers pay
  // a full reimport + CUDA re-init per worker there, the same constraint
  // mps (also spawn-only) already works around below. More cores doesn't
  // change that, so this stays workers: 0 regardless of CPU count.
  cuda_windows: {
    dataset: { batch_size: 32, workers: 0, use_multithreading: true, max_workers: 8, use_blur: true },
    model: { type: 'yolov5', device: 'cuda:0' },
    inference: { use_multithreading: true, max_workers: 8, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
  cpu: {
    dataset: { batch_size: 1, workers: 0, use_multithreading: false, max_workers: 1, use_blur: true },
    model: { type: 'yolov5', device: 'cpu' },
    inference: { use_multithreading: false, max_workers: 1, apply_nms_batchwise: true, apply_length_estimates_batchwise: false, length_config: { type: 'unet', weights: null } },
  },
}

export const BATCH_SIZE_OPTIONS = [1, 2, 4, 8, 16, 32, 64, 128]
export const MAX_WORKERS_OPTIONS = [1, 2, 4, 8, 16]
export const WORKERS_OPTIONS = [0, 1, 2, 4, 8, 10, 16]

// Which PLATFORM_PRESETS entry to use. Device alone isn't enough for cuda:
// there's no plain 'cuda' preset, only 'cuda_linux'/'cuda_windows' - a
// Windows CUDA box needs the spawn-safe one, and only the backend's
// sys.platform check is a reliable way to tell those apart (see
// fisheye_ui/routes/platform.py). Non-cuda devices have a single preset
// each and pass straight through.
export function presetKeyFor(device, os) {
  if (device !== 'cuda') return device
  return os === 'windows' ? 'cuda_windows' : 'cuda_linux'
}