import { MAP_COLORS } from './crystalColors'

const CDN_GEO_BASE = 'https://geo.datav.aliyun.com/areas_v3/bound'
const geoCache = new Map()

const HAINAN_ADCODE = '460000'
const SANSCHA_FEATURE_NAME = '三沙市'

/** 省级 drill-down 时从主图排除的区划（如三沙市另绘附图） */
const EXCLUDED_PROVINCE_REGIONS = {
  [HAINAN_ADCODE]: new Set([SANSCHA_FEATURE_NAME]),
}

/** 三沙附图只保留西沙/中沙核心岛礁，避免南海大范围坐标压扁主图 */
const SANSCHA_INSET_BOUNDS = {
  minLon: 111.0,
  maxLon: 117.2,
  minLat: 15.75,
  maxLat: 17.15,
}

export function isHainanProvince(provinceName, adcode) {
  return String(adcode || '') === HAINAN_ADCODE || provinceName === '海南省'
}

export function prepareGeoJson(adcode, geoJson) {
  const excluded = EXCLUDED_PROVINCE_REGIONS[String(adcode)]
  if (!excluded?.size || !geoJson?.features?.length) return geoJson
  const features = geoJson.features.filter(
    (feature) => !excluded.has(feature.properties?.name),
  )
  if (features.length === geoJson.features.length) return geoJson
  return { ...geoJson, features }
}

function pointInBounds([lon, lat], bounds) {
  return (
    lon >= bounds.minLon
    && lon <= bounds.maxLon
    && lat >= bounds.minLat
    && lat <= bounds.maxLat
  )
}

function filterRingByBounds(ring, bounds) {
  const pts = (ring || []).filter((pt) => pointInBounds(pt, bounds))
  return pts.length >= 3 ? pts : null
}

function filterPolygonByBounds(polygon, bounds) {
  return (polygon || [])
    .map((ring) => filterRingByBounds(ring, bounds))
    .filter(Boolean)
}

function cropFeatureGeometry(feature, bounds) {
  const geom = feature?.geometry
  if (!geom) return null
  if (geom.type === 'Polygon') {
    const rings = filterPolygonByBounds(geom.coordinates, bounds)
    return rings.length ? { type: 'Polygon', coordinates: rings } : null
  }
  if (geom.type === 'MultiPolygon') {
    const polys = (geom.coordinates || [])
      .map((poly) => filterPolygonByBounds(poly, bounds))
      .filter((poly) => poly.length)
    return polys.length ? { type: 'MultiPolygon', coordinates: polys } : null
  }
  return null
}

/** 三沙市附图 GeoJSON（裁剪后用于右下角小图） */
export function buildHainanSanshaInsetGeoJson(fullGeoJson) {
  const feature = fullGeoJson?.features?.find(
    (item) => item.properties?.name === SANSCHA_FEATURE_NAME,
  )
  if (!feature) return null
  const geometry = cropFeatureGeometry(feature, SANSCHA_INSET_BOUNDS)
  if (!geometry) return null
  return {
    type: 'FeatureCollection',
    features: [{ ...feature, geometry }],
  }
}

/** 个别省份的 map 布局微调 */
export function getProvinceMapLayoutOverrides(provinceName, adcode) {
  if (isHainanProvince(provinceName, adcode)) {
    return {
      zoom: 1.72,
      layoutCenter: ['48%', '52%'],
      layoutSize: '112%',
      aspectScale: 0.68,
    }
  }
  return {}
}

/** 三沙附图 series 布局 */
export function getHainanSanshaInsetLayout() {
  return {
    center: [112.35, 16.45],
    zoom: 2.8,
    layoutCenter: ['84%', '87%'],
    layoutSize: '26%',
    aspectScale: 0.9,
  }
}

const REGION_NAME_ALIASES = {
  凉山彝族自治州: ['凉山州', '凉山'],
  甘孜藏族自治州: ['甘孜州', '甘孜'],
  阿坝藏族羌族自治州: ['阿坝州', '阿坝'],
  自贡市: ['自贡'],
}

export function normalizeRegionName(name) {
  return String(name || '')
    .trim()
    .replace(/壮族自治区|回族自治区|维吾尔自治区|特别行政区/g, '')
    .replace(/自治区|自治州|地区|盟/g, '')
    .replace(/市$|区$|县$/, '')
}

function regionNamesEquivalent(left, right) {
  if (!left || !right) return false
  if (left === right) return true
  if (left.startsWith(right) || right.startsWith(left)) return true
  if (normalizeRegionName(left) === normalizeRegionName(right)) return true
  for (const [canonical, aliases] of Object.entries(REGION_NAME_ALIASES)) {
    const names = [canonical, ...aliases]
    if (names.includes(left) && names.includes(right)) return true
  }
  return false
}

export function findRegionStat(geoName, regions) {
  if (!geoName || !regions?.length) return null
  const direct = regions.find((item) => item.name === geoName)
  if (direct) return direct
  return (
    regions.find((item) => regionNamesEquivalent(geoName, item.name)) || null
  )
}

const GEO_FETCH_TIMEOUT_MS = 8000

export async function fetchGeoFrom(url, timeoutMs = GEO_FETCH_TIMEOUT_MS) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(url, { signal: controller.signal })
    if (!response.ok) return null
    const json = await response.json()
    if (!json?.features?.length) return null
    return json
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

export async function loadGeoJson(adcode) {
  const key = String(adcode)
  if (geoCache.has(key)) return geoCache.get(key)

  // 静态文件优先，避免 /api/geo 在 MySQL 繁忙时占满 Gunicorn 线程导致省级下钻卡死
  const sources = [
    `/geo/${key}_full.json`,
    `/api/geo/${key}`,
    `${CDN_GEO_BASE}/${key}_full.json`,
  ]

  for (const url of sources) {
    const json = await fetchGeoFrom(url)
    if (json?.features?.length) {
      geoCache.set(key, json)
      return json
    }
  }

  throw new Error(`地图数据加载失败: ${adcode}`)
}

export function matchRegionName(geoName, regions) {
  if (!geoName) return ''
  const matched = findRegionStat(geoName, regions)
  return matched?.name || geoName
}

export function findFeatureByName(geoJson, name) {
  if (!geoJson?.features?.length || !name) return null
  return (
    geoJson.features.find((feature) => feature.properties?.name === name) ||
    geoJson.features.find((feature) => {
      const geoName = feature.properties?.name || ''
      return (
        geoName.startsWith(name) ||
        name.startsWith(geoName) ||
        normalizeRegionName(geoName) === normalizeRegionName(name)
      )
    }) ||
    null
  )
}

export function getFeatureCenter(feature) {
  const props = feature?.properties || {}
  return props.center || props.centroid || null
}

export function failureRateToMapColor(failureRate) {
  if (failureRate == null || failureRate < 0) return MAP_COLORS.none
  if (failureRate < 1) return MAP_COLORS.veryLow
  if (failureRate < 3) return MAP_COLORS.low
  if (failureRate < 4) return MAP_COLORS.mid
  return MAP_COLORS.high
}

function buildRegionMapStyle(areaColor) {
  return {
    itemStyle: { areaColor },
    emphasis: {
      itemStyle: {
        areaColor,
        borderColor: '#fff',
        borderWidth: 1.2,
      },
      label: { show: true, color: '#111827', fontWeight: 600 },
    },
  }
}

export function buildMapSeriesData(geoJson, regions) {
  return (geoJson?.features || []).map((feature) => {
    const geoName = feature.properties?.name || ''
    const matched = findRegionStat(geoName, regions)
    const failureRate = matched?.failure_rate ?? null
    const areaColor = failureRateToMapColor(failureRate)
    return {
      name: geoName,
      value: failureRate ?? -1,
      dataName: matched?.name || geoName,
      qualified_count: matched?.qualified_count ?? 0,
      unqualified_count: matched?.unqualified_count ?? 0,
      total_count: matched?.total_count ?? 0,
      failure_rate: failureRate,
      hasData: Boolean(matched && matched.total_count > 0),
    }
  })
}

/** 固定分段：绿占窄区间，红为主（与 maxRate 无关，便于跨省对比） */
export function buildVisualMapPieces(_maxRate) {
  return [
    { min: -1, max: -1, label: '无数据', color: MAP_COLORS.none },
    { min: 0, max: 1, label: '<1% 极低', color: MAP_COLORS.veryLow },
    { min: 1, max: 3, label: '1–3% 较低', color: MAP_COLORS.low },
    { min: 3, max: 4, label: '3–4% 中等', color: MAP_COLORS.mid },
    { min: 4, max: 100, label: '>4% 较高', color: MAP_COLORS.high },
  ]
}
