const screenInitial = document.getElementById('screen-initial')
const screenProgress = document.getElementById('screen-progress')
const statusPhase = document.getElementById('status-phase')
const statusDetail = document.getElementById('status-detail')
const barFill = document.getElementById('bar-fill')
const errorText = document.getElementById('error-text')
const retryButtons = document.getElementById('retry-buttons')

function formatBytes(n) {
  if (!n) return ''
  const gb = n / 1e9
  return gb >= 0.1 ? `${gb.toFixed(1)}GB` : `${(n / 1e6).toFixed(0)}MB`
}

function showProgress() {
  screenInitial.classList.remove('active')
  screenProgress.classList.add('active')
  errorText.style.display = 'none'
  retryButtons.style.display = 'none'
  setPhase('downloading', 0, 0)
}

function setPhase(phase, downloaded, total, partIndex, totalParts) {
  const labels = {
    downloading: 'Downloading…',
    verifying: 'Verifying…',
    extracting: 'Extracting…',
  }
  const label = labels[phase] || 'Working…'
  statusPhase.textContent = totalParts > 1 ? `${label} (part ${partIndex} of ${totalParts})` : label

  if (phase === 'extracting' || !total) {
    barFill.classList.add('indeterminate')
    barFill.style.width = ''
    statusDetail.textContent = ''
  } else {
    barFill.classList.remove('indeterminate')
    const pct = Math.min(100, Math.round((downloaded / total) * 100))
    barFill.style.width = `${pct}%`
    statusDetail.textContent = `${formatBytes(downloaded)} / ${formatBytes(total)}`
  }
}

function showError(message) {
  errorText.textContent = message
  errorText.style.display = 'block'
  retryButtons.style.display = 'flex'
  barFill.classList.remove('indeterminate')
  barFill.style.width = '0%'
}

document.getElementById('download-btn').addEventListener('click', () => {
  showProgress()
  window.fisheyeElectron.startGpuSetupDownload()
})

document.getElementById('local-file-btn').addEventListener('click', async () => {
  const filePaths = await window.fisheyeElectron.pickGpuRuntimeFiles()
  if (!filePaths || filePaths.length === 0) return
  showProgress()
  window.fisheyeElectron.startGpuSetupFromFiles(filePaths)
})

document.getElementById('retry-btn').addEventListener('click', () => {
  screenProgress.classList.remove('active')
  screenInitial.classList.add('active')
})

window.fisheyeElectron.onGpuSetupProgress(({ phase, downloaded, total, partIndex, totalParts }) => {
  setPhase(phase, downloaded, total, partIndex, totalParts)
})

window.fisheyeElectron.onGpuSetupError(({ message }) => {
  showError(message)
})

window.fisheyeElectron.onGpuSetupComplete(() => {
  statusPhase.textContent = 'Done — starting FishEye…'
  statusDetail.textContent = ''
  barFill.classList.remove('indeterminate')
  barFill.style.width = '100%'
})
