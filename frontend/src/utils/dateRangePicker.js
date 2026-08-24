/** 日期范围选择：禁止未来日期 + 常用快捷项 */

function startOfDay(date) {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d
}

function formatYMD(date) {
  const d = startOfDay(date)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function getTodayYMD() {
  return formatYMD(new Date())
}

/** Element Plus disabled-date：不可选今天之后 */
export function disabledFutureDate(time) {
  return startOfDay(time).getTime() > startOfDay(new Date()).getTime()
}

function clampEndToToday(end) {
  const today = startOfDay(new Date())
  return startOfDay(end).getTime() > today.getTime() ? today : startOfDay(end)
}

function yearRange(year) {
  const start = startOfDay(new Date(year, 0, 1))
  const end = clampEndToToday(new Date(year, 11, 31))
  return [start, end]
}

function rollingRange(days) {
  const end = startOfDay(new Date())
  const start = new Date(end)
  start.setDate(start.getDate() - days + 1)
  return [start, end]
}

function rollingMonths(months) {
  const end = startOfDay(new Date())
  const start = new Date(end)
  start.setMonth(start.getMonth() - months)
  return [start, end]
}

export const dateRangePickerShortcuts = [
  { text: '2025年', value: () => yearRange(2025) },
  { text: '2024年', value: () => yearRange(2024) },
  { text: '一年内', value: () => rollingRange(365) },
  { text: '半年内', value: () => rollingMonths(6) },
  { text: '一个月内', value: () => rollingMonths(1) },
]
