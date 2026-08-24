export function buildMapDataFromStats(stats, scope = '全国') {
  const provinces = stats?.provinces || {}
  const regions = Object.entries(provinces)
    .map(([name, info]) => {
      const qualified = info.qualified || 0
      const unqualified = info.unqualified || 0
      const total = qualified + unqualified
      return {
        name,
        qualified_count: qualified,
        unqualified_count: unqualified,
        total_count: total,
        failure_rate: total ? Math.round((unqualified / total) * 10000) / 100 : 0,
      }
    })
    .filter((item) => item.total_count > 0)
    .sort((a, b) => b.failure_rate - a.failure_rate)

  const rates = regions.map((item) => item.failure_rate)
  return {
    level: 'province',
    scope,
    regions,
    max_failure_rate: rates.length ? Math.max(...rates) : 0,
    min_failure_rate: rates.length ? Math.min(...rates) : 0,
  }
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function isMapApiLoadingError(err) {
  const status = err?.response?.status
  const body = err?.response?.data
  if (status === 503 && body?.loading) return true
  return status === 502 || status === 504
}
