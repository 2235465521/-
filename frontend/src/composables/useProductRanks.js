import { ref } from 'vue'
import { getProductRanks } from '@/api'
import { formatDateRangeLabel, formatScopeLabel } from '@/utils/format'
import { dataMatchesScope, formatRankLoadingText } from '@/composables/rankScope'

const CACHE_SCHEMA = 2
const MAX_RETRIES = 5

function dateKey(dateRange) {
  if (!dateRange?.[0] || !dateRange?.[1]) return ''
  return `${dateRange[0]}|${dateRange[1]}`
}

function isRetryableError(err) {
  const status = err?.response?.status
  if (status === 502 || status === 503 || status === 504) return true
  const msg = err?.message || ''
  return msg.includes('timeout') || msg.includes('Network Error') || err?.code === 'ECONNABORTED'
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function isUsable(res) {
  if (!res || typeof res !== 'object' || res.loading) return false
  const total = Number(res.total || 0)
  const hasItems = (res.item_types?.length || 0) > 0
  const hasProducts = (res.top_failure_products?.length || 0) > 0
  const hasRepeat = (res.repeat_product_count || 0) > 0
  if (total <= 0) return hasItems || hasProducts || hasRepeat
  return hasItems || hasProducts || hasRepeat
}

const cache = ref(null)
const data = ref(null)
const loading = ref(false)
const loadError = ref('')
const needsBackendRefresh = ref(false)
let inflight = null
let loadSeq = 0

export function useProductRanks() {
  function cacheValid(province, city, dateRange) {
    return (
      cache.value
      && cache.value.timestamp
      && (Date.now() - cache.value.timestamp < 15000)
      && cache.value.schemaVersion === CACHE_SCHEMA
      && cache.value.province === province
      && (cache.value.city || '全部') === (city || '全部')
      && cache.value.dateKey === dateKey(dateRange)
      && dataMatchesScope(cache.value.data, province, city)
      && isUsable(cache.value.data)
    )
  }

  function markStaleIfNeeded(res) {
    needsBackendRefresh.value = Boolean(
      res && res.item_types?.length && res.item_types_total == null,
    )
  }

  function formatSummary(province, city, dateRange = null) {
    if (loading.value || !dataMatchesScope(data.value, province, city)) {
      return formatRankLoadingText(province, city)
    }
    if (loadError.value) return loadError.value
    if (!data.value) return '暂无产品榜单数据，请点击重试或稍后再试'
    const d = data.value
    const scope = formatScopeLabel(d.province, d.city)
    let text = `范围 ${scope} · 不合格 ${(d.total || 0).toLocaleString()} 项 · 高频产品 ${d.repeat_product_count || 0} 种`
    if (d.province !== '全部' || d.city !== '全部') {
      text += ' · 当前为筛选范围内统计'
    }
    const range = formatDateRangeLabel(dateRange)
    return range ? `${text} | 时间：${range}` : text
  }

  async function fetchRanks(province, city, dateRange) {
    let lastError = null
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
      try {
        const { data: res } = await getProductRanks(province, city, dateRange)
        if (res?.loading && attempt < MAX_RETRIES) {
          await sleep(2000 * (attempt + 1))
          continue
        }
        return res
      } catch (err) {
        lastError = err
        if (attempt < MAX_RETRIES && isRetryableError(err)) {
          await sleep(1500 * (attempt + 1))
          continue
        }
        throw err
      }
    }
    throw lastError
  }

  async function load(province, city, dateRange = null, force = false) {
    if (!force && cacheValid(province, city, dateRange)) {
      data.value = cache.value.data
      loadError.value = ''
      return data.value
    }

    const seq = ++loadSeq
    data.value = null
    loadError.value = ''
    loading.value = true

    if (inflight) {
      await inflight
      if (seq !== loadSeq) return data.value
      if (!force && cacheValid(province, city, dateRange)) {
        data.value = cache.value.data
        loading.value = false
        return data.value
      }
    }

    inflight = (async () => {
      try {
        const res = await fetchRanks(province, city, dateRange)
        if (seq !== loadSeq) return null

        if (res?.loading || !dataMatchesScope(res, province, city)) {
          data.value = null
          loadError.value = res?.message || formatRankLoadingText(province, city)
          return null
        }
        markStaleIfNeeded(res)
        if (!isUsable(res)) {
          data.value = null
          loadError.value = '产品榜单数据为空，请稍后重试'
          cache.value = null
          return null
        }
        data.value = res
        cache.value = {
          timestamp: Date.now(),
          schemaVersion: CACHE_SCHEMA,
          province,
          city,
          dateKey: dateKey(dateRange),
          data: res,
        }
        loadError.value = ''
        return res
      } catch (err) {
        if (seq !== loadSeq) return null
        data.value = null
        const msg = err?.response?.data?.message || err?.message || '产品榜单加载失败'
        loadError.value = `${msg}（可点击重试）`
        return null
      } finally {
        if (seq === loadSeq) {
          loading.value = false
        }
        inflight = null
      }
    })()
    return inflight
  }

  return {
    data,
    loading,
    loadError,
    needsBackendRefresh,
    load,
    cacheValid,
    formatSummary,
    dataMatchesScope,
  }
}
