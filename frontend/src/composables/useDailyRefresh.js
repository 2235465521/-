const DAILY_REFRESH_KEY = 'shipin_daily_data_refresh_at'
export const DAILY_REFRESH_MS = 24 * 60 * 60 * 1000

export function shouldRunDailyRefresh() {
  const last = Number(localStorage.getItem(DAILY_REFRESH_KEY) || 0)
  return !last || Date.now() - last >= DAILY_REFRESH_MS
}

export function markDailyRefreshDone() {
  localStorage.setItem(DAILY_REFRESH_KEY, String(Date.now()))
}

/** 开发人员强制刷新时调用，跳过一次每日限流 */
export function markForceRefreshDone() {
  markDailyRefreshDone()
}
