import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 120000,
})

export default api

export const getHealth = () => api.get('/api/health', { timeout: 8000 })
export const getStats = (dateRange = null) =>
  api.get('/api/stats', { params: buildDateParams(dateRange) })
export const getStatus = () => api.get('/api/status')
export const startScan = (full = false) => api.post('/api/scan', null, { params: { full: full ? '1' : '0' } })
export const getProvinces = () => api.get('/api/provinces', { timeout: 15000 })
export const getCities = (province = '全部') =>
  api.get('/api/cities', { params: { province }, timeout: 15000 })
export const getData = (params) => api.get('/api/data', { params })
export const getOverviewChart = (province, city, dateRange) =>
  api.get('/api/overview-chart', {
    params: { province, city, ...buildDateParams(dateRange) },
    timeout: 30000,
  })
export const getOverviewMap = (province = '全部', dateRange = null, city = '') =>
  api.get('/api/overview-map', { params: { province, city, ...buildDateParams(dateRange) } })
export const getCityInsights = (province, city = '全部', dateRange = null, limit = 3) =>
  api.get('/api/city-insights', {
    params: { province, city: city || '全部', limit, ...buildDateParams(dateRange) },
  })
export const getProvinceTrend = (province, dateRange = null) =>
  api.get('/api/province-trend', { params: { province, ...buildDateParams(dateRange) } })
export const getAnalytics = (province, city, minViolations = 2, dateRange = null, minRepeatViolations = 5) =>
  api.get('/api/analytics', {
    params: {
      province,
      city,
      min_violations: minViolations,
      min_repeat_violations: minRepeatViolations,
      ...buildDateParams(dateRange),
    },
    timeout: 180000,
  })
export const getUnitRanks = (province, city, dateRange = null) =>
  api.get('/api/rank/units', {
    params: { province, city, ...buildDateParams(dateRange) },
    timeout: 120000,
  })
export const getProductRanks = (province, city, dateRange = null) =>
  api.get('/api/rank/products', {
    params: { province, city, ...buildDateParams(dateRange) },
    timeout: 120000,
  })
export const getCompanyStats = (q, province, city, dateRange = null) =>
  api.get('/api/company-stats', {
    params: { q, province, city, ...buildDateParams(dateRange) },
  })

function buildDateParams(dateRange) {
  if (!dateRange?.[0] || !dateRange?.[1]) return {}
  return { date_from: dateRange[0], date_to: dateRange[1] }
}
export const openSourceFile = (path) => api.post('/api/open-file', { path })
