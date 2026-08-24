import { ref } from 'vue'
import { getCities, getHealth, getProvinces, getStats } from '@/api'

const provinces = ref(null)
const citiesByProvince = ref({})
const stats = ref(null)
const apiError = ref('')
let provincesInflight = null
let statsInflight = null
const citiesInflight = {}

function markError(err) {
  const status = err?.response?.status
  const msg = err?.response?.data?.message || err?.message || '无法连接后端 API'
  if (status === 502 || status === 504) {
    apiError.value = '后端繁忙或正在计算统计，正在自动重试…'
  } else if (msg.includes('Network Error') || msg.includes('ECONNREFUSED') || err?.code === 'ERR_NETWORK') {
    apiError.value = '后端服务无响应'
  } else {
    apiError.value = msg
  }
  throw err
}

function shouldRetryStats(data) {
  return Boolean(data?.cache_loading || data?.module_loading)
}

function shouldRetryError(err) {
  const status = err?.response?.status
  const body = err?.response?.data
  return (status === 503 && body?.loading) || status === 502 || status === 504
}

async function pingBackend() {
  const { data } = await getHealth()
  return Boolean(data?.ok || data?.service)
}

export function useAppData() {
  async function ensureProvinces(force = false) {
    if (!force && provinces.value) return provinces.value
    if (provincesInflight) return provincesInflight
    provincesInflight = getProvinces()
      .then(({ data }) => {
        apiError.value = ''
        provinces.value = data
        return data
      })
      .catch((err) => {
        if (shouldRetryError(err)) {
          setTimeout(() => ensureProvinces(true), 2500)
          return provinces.value
        }
        markError(err)
      })
      .finally(() => {
        provincesInflight = null
      })
    return provincesInflight
  }

  async function ensureCities(province = '全部', force = false) {
    const key = province || '全部'
    if (!force && citiesByProvince.value[key]) return citiesByProvince.value[key]
    if (citiesInflight[key]) return citiesInflight[key]
    citiesInflight[key] = getCities(key)
      .then(({ data }) => {
        apiError.value = ''
        citiesByProvince.value = { ...citiesByProvince.value, [key]: data }
        return data
      })
      .catch((err) => {
        if (shouldRetryError(err)) {
          setTimeout(() => ensureCities(province, true), 2500)
          return citiesByProvince.value[key]
        }
        markError(err)
      })
      .finally(() => {
        delete citiesInflight[key]
      })
    return citiesInflight[key]
  }

  async function ensureStats(force = false, dateRange = null) {
    const dateKey = dateRange?.[0] && dateRange?.[1] ? `${dateRange[0]}~${dateRange[1]}` : 'all'
    const cacheKey = `${dateKey}|${stats.value?.count_mode || ''}`
    if (
      !force &&
      stats.value?.count_mode === 'item' &&
      !shouldRetryStats(stats.value) &&
      stats.value?._cacheKey === cacheKey
    ) {
      return stats.value
    }
    if (statsInflight) return statsInflight
    statsInflight = getStats(dateRange)
      .then(({ data }) => {
        apiError.value = ''
        stats.value = { ...data, _cacheKey: cacheKey }
        if (shouldRetryStats(data)) {
          setTimeout(() => ensureStats(true), 2500)
        }
        return data
      })
      .catch((err) => {
        if (shouldRetryError(err)) {
          setTimeout(() => ensureStats(true), 2500)
          return stats.value
        }
        markError(err)
      })
      .finally(() => {
        statsInflight = null
      })
    return statsInflight
  }

  function invalidate() {
    provinces.value = null
    citiesByProvince.value = {}
    stats.value = null
  }

  return {
    provinces,
    citiesByProvince,
    stats,
    apiError,
    ensureProvinces,
    ensureCities,
    ensureStats,
    invalidate,
  }
}
