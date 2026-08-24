import { formatScopeLabel } from '@/utils/format'

export function normalizeScopePart(value) {
  return value || '全部'
}

/** 榜单 payload 的 province/city 是否与当前筛选一致 */
export function dataMatchesScope(payload, province, city) {
  if (!payload || payload.loading) return false
  return (
    normalizeScopePart(payload.province) === normalizeScopePart(province)
    && normalizeScopePart(payload.city) === normalizeScopePart(city)
  )
}

export function formatRankLoadingText(province, city) {
  return `正在加载${formatScopeLabel(province, city)}数据…`
}
