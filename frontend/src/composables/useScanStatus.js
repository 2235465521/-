import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getStatus, startScan } from '@/api'

const status = ref({})
const polling = ref(null)
let pollDelayTimer = null
let pollInFlight = false
let wasRunning = false
let manualScanActive = false

export function useScanStatus(onManualScanComplete) {
  function stopScanPolling() {
    if (polling.value) {
      clearInterval(polling.value)
      polling.value = null
    }
  }

  function startScanPolling(intervalMs = 2000) {
    if (!polling.value) {
      polling.value = setInterval(pollStatus, intervalMs)
    }
  }

  function schedulePoll(delayMs = 2000) {
    if (pollDelayTimer) clearTimeout(pollDelayTimer)
    pollDelayTimer = setTimeout(() => {
      pollDelayTimer = null
      pollStatus()
    }, delayMs)
  }

  async function pollStatus() {
    if (pollInFlight) return
    pollInFlight = true
    try {
      const { data } = await getStatus()
      status.value = data
      const running = Boolean(data.running)

      if (data.cache_loading || data.module_loading) {
        schedulePoll(2000)
        wasRunning = running
        return
      }

      if (running) {
        startScanPolling(2000)
      } else {
        stopScanPolling()
        if (wasRunning && manualScanActive) {
          manualScanActive = false
          onManualScanComplete?.()
        } else if (wasRunning) {
          manualScanActive = false
        }
      }
      wasRunning = running
    } catch (err) {
      const httpStatus = err?.response?.status
      const body = err?.response?.data
      if (httpStatus === 503 && body?.loading) {
        status.value = { module_loading: true, cache_loading: true, message: body.message || '后端模块加载中…' }
        schedulePoll(2000)
        return
      }
      status.value = { message: '无法连接后端，请确认后端已启动' }
      schedulePoll(60000)
    } finally {
      pollInFlight = false
    }
  }

  async function triggerScan() {
    manualScanActive = true
    try {
      const { data } = await startScan()
      if (data.ok) {
        ElMessage.success(data.message)
        await pollStatus()
        if (status.value.running) {
          startScanPolling(1000)
        } else if (manualScanActive) {
          manualScanActive = false
          onManualScanComplete?.()
        }
      } else {
        manualScanActive = false
      }
    } catch (err) {
      manualScanActive = false
      ElMessage.error(err.response?.data?.message || '扫描启动失败')
    }
  }

  onMounted(async () => {
    await pollStatus()
    if (status.value.running) {
      startScanPolling(2000)
    }
  })

  onUnmounted(() => {
    stopScanPolling()
    if (pollDelayTimer) clearTimeout(pollDelayTimer)
  })

  return { status, pollStatus, triggerScan }
}
