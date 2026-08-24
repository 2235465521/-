import { ref } from 'vue'
import { getOverviewChart } from '@/api'

const chartCache = ref({})
const chart = ref(null)
const loading = ref(false)
const indexBuilding = ref(false)
const MAX_RETRIES = 3
let inflight = null

function isRetryableError(err) {
  const status = err?.response?.status
  const body = err?.response?.data
  if (status === 503 && body?.loading) return true
  if (!err?.response) return true
  return status === 502 || status === 504
}

function retryDelay(err) {
  const body = err?.response?.data
  return body?.message?.includes('索引') ? 2500 : 3000
}

function dateKey(dateRange) {
  if (!dateRange?.[0] || !dateRange?.[1]) return 'all'
  return `${dateRange[0]}~${dateRange[1]}`
}

export function useOverview() {
  function cacheKey(province, city, dateRange) {
    return `v10|${province || '全部'}|${city || '全部'}|${dateKey(dateRange)}`
  }

  async function loadChart(province = '全部', city = '全部', force = false, dateRange = null, attempt = 0) {
    const key = cacheKey(province, city, dateRange)
    if (!force && chartCache.value[key]) {
      chart.value = chartCache.value[key]
      indexBuilding.value = false
      return chart.value
    }

    if (inflight) {
      await inflight
      if (!force && chartCache.value[key]) {
        chart.value = chartCache.value[key]
        indexBuilding.value = false
        return chart.value
      }
    }

    loading.value = true
    inflight = getOverviewChart(province, city, dateRange)
      .then(({ data }) => {
        chartCache.value = { ...chartCache.value, [key]: data }
        chart.value = data
        indexBuilding.value = false
        return data
      })
      .catch((err) => {
        if (isRetryableError(err) && attempt < MAX_RETRIES) {
          indexBuilding.value = Boolean(err?.response?.data?.loading)
          return new Promise((resolve) => {
            setTimeout(() => {
              resolve(loadChart(province, city, force, dateRange, attempt + 1))
            }, retryDelay(err))
          })
        }
        indexBuilding.value = false
        throw err
      })
      .finally(() => {
        loading.value = false
        inflight = null
      })
    return inflight
  }

  function invalidate() {
    chartCache.value = {}
    chart.value = null
    indexBuilding.value = false
  }

  return { chart, loading, indexBuilding, loadChart, invalidate }
}
