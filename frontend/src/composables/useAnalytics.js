import { ref } from 'vue'
import { getAnalytics } from '@/api'
import { formatDateRangeLabel, formatScopeLabel } from '@/utils/format'

const ANALYTICS_SCHEMA = 47
const MAX_RETRIES = 15

export function isUsableAnalytics(res) {
  if (!res || typeof res !== 'object' || res.loading) return false
  const total = Number(res.total || 0)
  const hasItems = (res.item_types?.length || 0) > 0
  const hasProducts = (res.top_failure_products?.length || 0) > 0
  const hasRepeat = (res.repeat_product_count || 0) > 0
  if (total <= 0) return hasItems || hasProducts || hasRepeat
  return hasItems || hasProducts || hasRepeat
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

const cache = ref(null)
const data = ref(null)
const loading = ref(false)
const loadError = ref('')
const needsBackendRefresh = ref(false)
let inflight = null

export function useAnalytics() {
  function dateKey(dateRange) {
    if (!dateRange?.[0] || !dateRange?.[1]) return ''
    return `${dateRange[0]}|${dateRange[1]}`
  }

  function cacheValid(province, city, dateRange) {
    return (
      cache.value &&
      cache.value.schemaVersion === ANALYTICS_SCHEMA &&
      cache.value.province === province &&
      (cache.value.city || '全部') === (city || '全部') &&
      cache.value.dateKey === dateKey(dateRange) &&
      isUsableAnalytics(cache.value.data)
    )
  }

  function markStaleIfNeeded(res) {
    needsBackendRefresh.value = Boolean(
      res && res.item_types?.length && res.item_types_total == null,
    )
  }

  function appendDateHint(text, dateRange) {
    const range = formatDateRangeLabel(dateRange)
    return range ? `${text} | 时间：${range}` : text
  }

  function formatSummary(province, city, dateRange = null) {
    if (loading.value && !data.value) return '正在加载统计数据，请稍候…'
    if (loadError.value && !data.value) return loadError.value
    if (!data.value) return '暂无统计数据，请点击重试或稍后再试'
    const scope = formatScopeLabel(province, city)
    const d = data.value
    let text = `范围 ${scope} · 不合格 ${(d.total || 0).toLocaleString()} 项 · 违规公司 ${d.repeat_company_count} 家 · 高频产品 ${d.repeat_product_count} 种`
    if (province !== '全部' || city !== '全部') {
      text += ' · 当前为筛选范围内统计'
    }
    return appendDateHint(text, dateRange)
  }

  function formatGreenSummary(province, city, dateRange = null) {
    if (loading.value && !data.value) return '正在加载绿榜数据，请稍候…'
    if (loadError.value && !data.value) return loadError.value
    if (!data.value) return '暂无绿榜数据，请点击重试或稍后再试'
    const scope = formatScopeLabel(province, city)
    const d = data.value
    const text = `范围 ${scope} · 全合格被抽检单位 ${(d.perfect_company_count || 0).toLocaleString()} 家 · 全合格生产单位 ${(d.perfect_manufacturer_count || 0).toLocaleString()} 家 · 至少 2 次抽检且无不合格`
    return appendDateHint(text, dateRange)
  }

  async function fetchAnalytics(province, city, dateRange) {
    let lastError = null
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
      try {
        const { data: res } = await getAnalytics(province, city, 2, dateRange)
        if (res?.loading && attempt < MAX_RETRIES) {
          await sleep(2500 * (attempt + 1))
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

    if (inflight) {
      await inflight
      if (!force && cacheValid(province, city, dateRange)) {
        data.value = cache.value.data
        loadError.value = ''
        return data.value
      }
    }

    loading.value = true
    loadError.value = ''
    inflight = (async () => {
      try {
        const res = await fetchAnalytics(province, city, dateRange)
        if (res?.loading) {
          loadError.value = res.message || '统计数据仍在计算中，请稍后点击重试'
          return data.value
        }
        markStaleIfNeeded(res)
        if (!isUsableAnalytics(res)) {
          loadError.value = '统计数据为空，请稍后重试'
          if (!data.value) cache.value = null
          return data.value
        }
        data.value = res
        cache.value = {
          schemaVersion: ANALYTICS_SCHEMA,
          province,
          city,
          dateKey: dateKey(dateRange),
          data: res,
        }
        loadError.value = ''
        return res
      } catch (err) {
        const msg = err?.response?.data?.message || err?.message || '统计数据加载失败'
        loadError.value = `${msg}（可点击重试）`
        if (!data.value) {
          cache.value = null
        }
        return data.value
      } finally {
        loading.value = false
        inflight = null
      }
    })()
    return inflight
  }

  function invalidate() {
    cache.value = null
    data.value = null
    loadError.value = ''
    needsBackendRefresh.value = false
  }

  return {
    loading,
    data,
    loadError,
    needsBackendRefresh,
    load,
    invalidate,
    formatSummary,
    formatGreenSummary,
    isUsableAnalytics,
    cacheValid,
  }
}
