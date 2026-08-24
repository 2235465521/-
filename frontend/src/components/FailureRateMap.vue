<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { MapChart } from 'echarts/charts'
import {
  GeoComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  MapChart,
  GeoComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])
import { getCityInsights, getOverviewMap, getProvinceTrend } from '@/api'
import CityInsightPanel from '@/components/CityInsightPanel.vue'
import { useAppData } from '@/composables/useAppData'
import { PROVINCE_ADCODES } from '@/data/provinceAdcodes'
import { buildMapDataFromStats, isMapApiLoadingError, sleep } from '@/utils/mapData'
import {
  buildHainanSanshaInsetGeoJson,
  buildMapSeriesData,
  buildVisualMapPieces,
  getHainanSanshaInsetLayout,
  getProvinceMapLayoutOverrides,
  isHainanProvince,
  loadGeoJson,
  matchRegionName,
  prepareGeoJson,
} from '@/utils/mapGeo'

const props = defineProps({
  dateRange: { type: Array, default: null },
})

const emit = defineEmits(['scope-change'])

const { stats, ensureStats } = useAppData()

const chartRef = ref(null)
const chartAlive = ref(true)
const loading = ref(false)
const mapError = ref('')
const mapHint = ref('')
const currentProvince = ref('')
const currentCity = ref('')
const mapScope = ref('全国')
const mapMeta = ref({ max_failure_rate: 0, min_failure_rate: 0 })
const regionInsightsLoading = ref(false)
const regionInsights = ref(null)
const regionTopLimit = ref(3)

// Province trend sparkline state
const trendLoading = ref(false)
const trendData = ref(null)
const trendStatus = ref('')
const hoveredPoint = ref(null)

const trendStatusClass = computed(() => {
  if (trendStatus.value === '持续恶化') return 'danger'
  if (trendStatus.value === '逐步改善') return 'success'
  return 'info'
})

const sparklineColor = computed(() => {
  if (trendStatus.value === '持续恶化') return '#ef4444' // red
  if (trendStatus.value === '逐步改善') return '#10b981' // green
  return '#0284c7' // blue
})

const sparklineGradientId = computed(() => {
  return `sparkline-grad-${currentProvince.value || 'temp'}`
})

const points = computed(() => {
  if (!trendData.value || trendData.value.length === 0) return []
  const n = trendData.value.length
  const width = 200
  const height = 45
  const padding = 6
  
  const rates = trendData.value.map(t => t.failure_rate)
  const min = Math.min(...rates)
  const max = Math.max(...rates)
  const range = max - min
  
  return trendData.value.map((t, i) => {
    const x = i * (width / (n - 1))
    let y = height / 2
    if (range > 0) {
      y = padding + ((max - t.failure_rate) / range) * (height - 2 * padding)
    }
    return { x, y, data: t }
  })
})

const linePath = computed(() => {
  const pts = points.value
  if (pts.length === 0) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
})

const areaPath = computed(() => {
  const pts = points.value
  if (pts.length === 0) return ''
  const first = pts[0]
  const last = pts[pts.length - 1]
  const height = 45
  return `${linePath.value} L ${last.x} ${height} L ${first.x} ${height} Z`
})

async function loadProvinceTrend(provinceName) {
  trendLoading.value = true
  hoveredPoint.value = null
  try {
    const { data } = await getProvinceTrend(provinceName, props.dateRange)
    trendData.value = data.trend || []
    trendStatus.value = data.status || ''
  } catch (err) {
    console.error('Failed to load province trend:', err)
    trendData.value = []
    trendStatus.value = ''
  } finally {
    trendLoading.value = false
  }
}

const drillDownActive = computed(() => Boolean(currentProvince.value))
const insightScopeLabel = computed(() => currentCity.value || currentProvince.value)

const legendSelected = ref({
  0: true, // 无数据
  1: true, // <1% 极低
  2: true, // 1-3% 较低
  3: true, // 3-4% 中等
  4: true, // >4% 较高
})

const legendItems = [
  { index: 4, label: '>4% 较高', color: '#f87171' },
  { index: 3, label: '3–4% 中等', color: '#fecdd3' },
  { index: 2, label: '1–3% 较低', color: '#a7f3d0' },
  { index: 1, label: '<1% 极低', color: '#34d399' },
  { index: 0, label: '无数据', color: '#e8eef4' },
]

function isValueActive(value) {
  if (value == null || value < 0) return legendSelected.value[0]
  if (value < 1) return legendSelected.value[1]
  if (value < 3) return legendSelected.value[2]
  if (value < 4) return legendSelected.value[3]
  return legendSelected.value[4]
}

function toggleLegend(index) {
  legendSelected.value[index] = !legendSelected.value[index]
  applyLegendSelection()
}

function applyLegendSelection() {
  if (chart && !chart.isDisposed?.()) {
    // 统一使用 setOption 更新 visualMap 的选中状态和序列标签的显示
    chart.setOption({
      visualMap: {
        selected: {
          ...legendSelected.value,
        },
      },
      series: (chart.getOption().series || []).map((s) => {
        if (s.type === 'map') {
          return {
            id: s.id,
            label: {
              formatter(params) {
                const active = isValueActive(params.value)
                return active ? params.name : ''
              },
            },
          }
        }
        return s
      }),
    })
  }
}

let chart = null
let resizeObserver = null
let dragMoved = false
let dragStart = null
let activeGeoJson = null
let activeFullGeoJson = null
let activeMapName = ''
let activeMapData = null
let activeMapScope = '全国'
let activeMapAdcode = ''
let activeMapOverrides = {}
let provinceViewState = null
let hoveredRegionEl = null
let mapRequestId = 0
let mapViewActive = true
let reviveSerial = 0

const MAP_HOVER_SCALE = 1.1

function beginMapRequest() {
  mapRequestId += 1
  return mapRequestId
}

function isMapRequestCurrent(requestId) {
  return mapViewActive && requestId === mapRequestId
}

function disposeChart() {
  resetMapHoverScale()
  resizeObserver?.disconnect()
  resizeObserver = null
  if (chart && !chart.isDisposed?.()) {
    chart.dispose()
  }
  chart = null
}

function ensureChartInstance() {
  if (!chartRef.value) return false
  if (chart && !chart.isDisposed?.()) return true
  disposeChart()
  chart = echarts.init(chartRef.value, null, { renderer: 'canvas' })
  resizeObserver = new ResizeObserver(handleResize)
  resizeObserver.observe(chartRef.value)
  return true
}

async function waitForChartContainer(maxFrames = 48) {
  for (let i = 0; i < maxFrames; i += 1) {
    const el = chartRef.value
    if (el && el.clientWidth > 0 && el.clientHeight > 0) return true
    await new Promise((resolve) => requestAnimationFrame(resolve))
  }
  return false
}

function isChartContainerReady() {
  const el = chartRef.value
  return Boolean(el && el.clientWidth > 0 && el.clientHeight > 0)
}

async function fetchMapData(province = '全部', city = '') {
  const scope = province === '全国' ? '全国' : province
  const statsData = stats.value || (await ensureStats().catch(() => null))

  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const { data } = await getOverviewMap(province, props.dateRange, city)
      if (data?.loading) {
        mapHint.value = data.message || '地图统计数据加载中…'
        await sleep(1500)
        continue
      }
      mapHint.value = ''
      return data
    } catch (err) {
      if (isMapApiLoadingError(err)) {
        mapHint.value = err?.response?.data?.message || '地图统计数据加载中…'
        if (scope === '全国' && statsData) {
          const fallback = buildMapDataFromStats(statsData)
          if (fallback.regions.length) return fallback
        }
        await sleep(err?.response?.data?.message?.includes('索引') ? 2500 : 2000)
        continue
      }
      if (scope === '全国' && statsData) {
        const fallback = buildMapDataFromStats(statsData)
        if (fallback.regions.length) {
          mapHint.value = '已使用汇总统计暂显，精确数据加载后将自动更新'
          return fallback
        }
      }
      throw err
    }
  }

  if (scope === '全国' && statsData) {
    const fallback = buildMapDataFromStats(statsData)
    if (fallback.regions.length) {
      mapHint.value = '已使用汇总统计暂显，精确数据加载后将自动更新'
      return fallback
    }
  }

  throw new Error('地图统计数据仍在加载，请稍后点击重试')
}

async function fetchRegionInsights(province, city = '全部', limit = regionTopLimit.value) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const { data } = await getCityInsights(province, city, props.dateRange, limit)
      if (data?.loading) {
        await sleep(2000)
        continue
      }
      return data
    } catch (err) {
      if (isMapApiLoadingError(err)) {
        await sleep(2000)
        continue
      }
      throw err
    }
  }
  throw new Error('城市数据仍在加载，请稍后重试')
}

function getRegionGraphicEl(params) {
  if (!chart || params?.seriesType !== 'map' || params.dataIndex == null || params.dataIndex < 0) {
    return null
  }
  const series = chart.getModel()?.getSeriesByIndex(params.seriesIndex)
  return series?.getData()?.getItemGraphicEl(params.dataIndex) ?? null
}

function resetMapHoverScale() {
  if (!hoveredRegionEl) return
  const orig = hoveredRegionEl.__mapHoverOrig
  if (orig) {
    hoveredRegionEl.originX = orig.originX
    hoveredRegionEl.originY = orig.originY
    hoveredRegionEl.scaleX = orig.scaleX
    hoveredRegionEl.scaleY = orig.scaleY
    hoveredRegionEl.z = orig.z
    hoveredRegionEl.z2 = orig.z2
  }
  delete hoveredRegionEl.__mapHoverOrig
  hoveredRegionEl = null
  chart?.getZr()?.refreshImmediately()
}

function applyMapHoverScale(params) {
  if (!chart || !params) return
  const el = getRegionGraphicEl(params)
  if (!el || el === hoveredRegionEl) return
  resetMapHoverScale()
  const rect = el.getBoundingRect()
  if (!rect.width || !rect.height) return
  el.__mapHoverOrig = {
    originX: el.originX ?? 0,
    originY: el.originY ?? 0,
    scaleX: el.scaleX ?? 1,
    scaleY: el.scaleY ?? 1,
    z: el.z ?? 0,
    z2: el.z2 ?? 0,
  }
  el.originX = rect.x + rect.width / 2
  el.originY = rect.y + rect.height / 2
  el.scaleX = el.__mapHoverOrig.scaleX * MAP_HOVER_SCALE
  el.scaleY = el.__mapHoverOrig.scaleY * MAP_HOVER_SCALE
  el.z2 = el.__mapHoverOrig.z2 + 10
  hoveredRegionEl = el
  chart.getZr().refreshImmediately()
}

function bindMapHoverScale() {
  chart.off('mouseover')
  chart.off('mouseout')
  chart.getZr().off('globalout')

  chart.on('mouseover', (params) => {
    if (params.seriesType !== 'map' || dragMoved || !params.name) return
    applyMapHoverScale(params)
  })
  chart.on('mouseout', (params) => {
    if (params.seriesType === 'map') resetMapHoverScale()
  })
  chart.getZr().on('globalout', resetMapHoverScale)
}

function bindMapInteractions(onRegionClick) {
  chart.off('click')
  chart.off('mousedown')
  chart.off('mousemove')
  chart.off('mouseup')

  chart.on('mousedown', (event) => {
    resetMapHoverScale()
    dragMoved = false
    dragStart = { x: event?.event?.offsetX ?? 0, y: event?.event?.offsetY ?? 0 }
  })
  chart.on('mousemove', (event) => {
    if (!dragStart || !event?.event) return
    const dx = Math.abs(event.event.offsetX - dragStart.x)
    const dy = Math.abs(event.event.offsetY - dragStart.y)
    if (dx > 4 || dy > 4) dragMoved = true
  })
  chart.on('mouseup', () => {
    dragStart = null
  })

  if (onRegionClick) {
    chart.on('click', (params) => {
      if (dragMoved || !params?.name) return
      onRegionClick(params)
    })
  }
}

function buildMapLayout(scope, overrides = {}) {
  return {
    roam: true,
    scaleLimit: { min: 0.6, max: 12 },
    zoom: scope === '全国' ? 1.15 : 1.2,
    layoutCenter: ['50%', '52%'],
    layoutSize: scope === '全国' ? '92%' : '88%',
    ...overrides,
  }
}

function buildMapTooltip() {
  return {
    trigger: 'item',
    formatter(params) {
      const data = params.data || {}
      if (!data.hasData) return `${params.name}<br/>暂无抽检数据`
      return [
        `${data.dataName || params.name}`,
        `不合格率：${data.failure_rate}%`,
        `合格：${(data.qualified_count || 0).toLocaleString()} 项`,
        `不合格：${(data.unqualified_count || 0).toLocaleString()} 项`,
        `合计：${(data.total_count || 0).toLocaleString()} 项`,
      ].join('<br/>')
    },
  }
}

function buildBaseMapSeries({
  mapName,
  geoJson,
  regions,
  scope,
  mapOverrides,
  roam = true,
  labelFontSize = 10,
  z = 1,
}) {
  return {
    type: 'map',
    map: mapName,
    ...buildMapLayout(scope, mapOverrides),
    roam,
    z,
    label: {
      show: scope !== '全国',
      color: '#475569',
      fontSize: labelFontSize,
      hideOverlap: scope !== '全国',
      formatter(params) {
        const active = isValueActive(params.value)
        return active ? params.name : ''
      },
    },
    itemStyle: {
      borderColor: 'rgba(255, 255, 255, 0.92)',
      borderWidth: 0.8,
    },
    data: buildMapSeriesData(geoJson, regions),
    selectedMode: false,
    emphasis: {
      focus: 'none',
      scale: false,
      label: { show: true, color: '#111827', fontWeight: 600 },
      itemStyle: {
        borderColor: '#fff',
        borderWidth: 1.2,
      },
    },
    blur: {
      itemStyle: { opacity: 1 },
    },
    select: { disabled: true },
  }
}

function buildHainanInsetSeries(fullGeoJson, mapName, regions) {
  const insetGeoJson = buildHainanSanshaInsetGeoJson(fullGeoJson)
  if (!insetGeoJson) return null
  const insetMapName = `${mapName}-sansha`
  echarts.registerMap(insetMapName, insetGeoJson)
  return {
    ...buildBaseMapSeries({
      mapName: insetMapName,
      geoJson: insetGeoJson,
      regions,
      scope: '海南省',
      mapOverrides: getHainanSanshaInsetLayout(),
      roam: false,
      labelFontSize: 9,
      z: 3,
    }),
    name: '三沙市',
    tooltip: buildMapTooltip(),
  }
}

function renderMap({
  geoJson,
  fullGeoJson,
  adcode,
  mapName,
  regions,
  scope,
  maxRate,
  onRegionClick,
  mapOverrides = {},
}) {
  if (!ensureChartInstance() || !geoJson || !isChartContainerReady()) return false
  resetMapHoverScale()
  activeGeoJson = geoJson
  activeFullGeoJson = fullGeoJson || null
  activeMapName = mapName
  activeMapScope = scope
  activeMapAdcode = adcode ? String(adcode) : ''
  activeMapOverrides = mapOverrides
  const isHainan = isHainanProvince(scope, adcode)
  const labelFontSize = isHainan ? 11 : 10
  const series = [
    buildBaseMapSeries({
      mapName,
      geoJson,
      regions,
      scope,
      mapOverrides,
      labelFontSize,
    }),
  ]
  if (isHainan && fullGeoJson) {
    const insetSeries = buildHainanInsetSeries(fullGeoJson, mapName, regions)
    if (insetSeries) series.push(insetSeries)
  }
  provinceViewState = series
  try {
    chart.setOption(
      {
        backgroundColor: 'transparent',
        tooltip: buildMapTooltip(),
        toolbox: {
          right: 12,
          top: 8,
          feature: {
            restore: { title: '重置视图' },
          },
          iconStyle: {
            borderColor: '#94a3b8',
          },
        },
        visualMap: {
          type: 'piecewise',
          pieces: buildVisualMapPieces(maxRate),
          show: false, // 隐藏原生图例，使用我们定制的更美观的 HTML 图例
          selected: {
            ...legendSelected.value,
          },
          outOfRange: {
            color: '#f1f5f9',
            opacity: 0,       // 将过滤区域及其中文标签完全隐藏（类似于消失的效果）
          },
        },
        graphic: isHainan
          ? [
              {
                type: 'text',
                left: '78%',
                top: '78%',
                style: {
                  text: '三沙市',
                  fill: '#64748b',
                  fontSize: 10,
                  fontWeight: 500,
                },
                z: 4,
              },
            ]
          : [],
        series,
      },
      true,
    )
    applyLegendSelection()
  } catch (err) {
    if (!isChartContainerReady()) return false
    throw err
  }
  bindMapHoverScale()
  bindMapInteractions(onRegionClick)
  return true
}

function buildChinaRegionClickHandler(mapData) {
  return async (params) => {
    const provinceName = matchRegionName(params.name, mapData.regions || [])
    if (!PROVINCE_ADCODES[provinceName]) return
    await showProvinceMap(provinceName)
  }
}

function buildProvinceRegionClickHandler(provinceName, mapData) {
  return async (params) => {
    const cityName = matchRegionName(params.name, mapData.regions || [])
    if (!cityName) return
    await selectCity(provinceName, cityName)
  }
}

async function restoreCachedMapView() {
  if (!activeMapData || !activeMapName || !activeGeoJson) return false
  if (!(await waitForChartContainer())) return false
  if (!ensureChartInstance()) return false

  mapError.value = ''
  chart.resize()

  try {
    if (currentProvince.value) {
      const provinceName = currentProvince.value
      const adcode = activeMapAdcode || PROVINCE_ADCODES[provinceName]
      if (!adcode) return false
      const mapName = activeMapName || `province-${adcode}`
      echarts.registerMap(mapName, activeGeoJson)
      return renderMap({
        geoJson: activeGeoJson,
        fullGeoJson: activeFullGeoJson,
        adcode,
        mapName,
        regions: activeMapData.regions || [],
        scope: provinceName,
        maxRate: activeMapData.max_failure_rate,
        mapOverrides: activeMapOverrides,
        onRegionClick: buildProvinceRegionClickHandler(provinceName, activeMapData),
      })
    }

    echarts.registerMap(activeMapName, activeGeoJson)
    return renderMap({
      geoJson: activeGeoJson,
      mapName: activeMapName,
      regions: activeMapData.regions || [],
      scope: activeMapScope || '全国',
      maxRate: activeMapData.max_failure_rate,
      onRegionClick: buildChinaRegionClickHandler(activeMapData),
    })
  } catch {
    disposeChart()
    return false
  }
}

async function reviveMapView() {
  const serial = ++reviveSerial
  mapViewActive = true
  mapError.value = ''
  await nextTick()
  if (serial !== reviveSerial) return
  if (!(await waitForChartContainer())) {
    await new Promise((resolve) => setTimeout(resolve, 80))
  }
  if (serial !== reviveSerial) return
  if (!(await waitForChartContainer())) return

  if (await restoreCachedMapView()) return

  const requestId = beginMapRequest()
  loading.value = true
  try {
    const mapData = activeMapData || (await fetchMapData('全部'))
    if (!isMapRequestCurrent(requestId) || serial !== reviveSerial) return
    await paintChinaMap(mapData, requestId)
  } catch (err) {
    if (!isMapRequestCurrent(requestId) || serial !== reviveSerial) return
    mapError.value = err?.response?.data?.message || err?.message || '地图加载失败'
  } finally {
    if (isMapRequestCurrent(requestId) && serial === reviveSerial) loading.value = false
  }
}

function resetProvinceView() {
  if (!provinceViewState?.length || !chart) return
  chart.setOption({ series: provinceViewState })
}

async function loadRegionInsights(province, city = '全部') {
  regionInsightsLoading.value = true
  try {
    regionInsights.value = await fetchRegionInsights(province, city)
  } catch (err) {
    if (!mapViewActive) return
    mapError.value = err?.response?.data?.message || err?.message || '榜单数据加载失败'
  } finally {
    regionInsightsLoading.value = false
  }
}

watch(regionTopLimit, () => {
  if (!currentProvince.value) return
  loadRegionInsights(currentProvince.value, currentCity.value || '全部')
})

async function selectCity(provinceName, cityName) {
  mapError.value = ''
  currentCity.value = cityName
  mapScope.value = `${provinceName} · ${cityName}`
  emit('scope-change', { province: provinceName, city: cityName })
  await loadRegionInsights(provinceName, cityName)
}

function clearCitySelection() {
  if (!currentProvince.value) return
  currentCity.value = ''
  mapScope.value = currentProvince.value
  emit('scope-change', { province: currentProvince.value, city: '全部' })
  loadRegionInsights(currentProvince.value, '全部')
}

async function paintChinaMap(mapData, requestId = mapRequestId) {
  const geoJson = await loadGeoJson('100000')
  if (!isMapRequestCurrent(requestId)) return
  echarts.registerMap('china-failure-map', geoJson)
  activeMapData = mapData
  mapMeta.value = mapData
  currentProvince.value = ''
  currentCity.value = ''
  regionInsights.value = null
  trendData.value = null
  trendStatus.value = ''
  hoveredPoint.value = null
  mapScope.value = '全国'
  emit('scope-change', { province: '全部', city: '全部' })
  if (!(await waitForChartContainer())) return
  renderMap({
    geoJson,
    mapName: 'china-failure-map',
    regions: mapData.regions || [],
    scope: '全国',
    maxRate: mapData.max_failure_rate,
    onRegionClick: buildChinaRegionClickHandler(mapData),
  })
}

async function showChinaMap() {
  const requestId = beginMapRequest()
  loading.value = true
  mapError.value = ''
  currentProvince.value = ''
  try {
    const mapData = await fetchMapData('全部')
    if (!isMapRequestCurrent(requestId)) return
    await paintChinaMap(mapData, requestId)
  } catch (err) {
    if (!isMapRequestCurrent(requestId)) return
    await ensureStats(false, props.dateRange).catch(() => null)
    const statsFallback = stats.value ? buildMapDataFromStats(stats.value) : null
    if (statsFallback?.regions?.length) {
      mapHint.value = '已使用汇总统计暂显'
      await paintChinaMap(statsFallback, requestId)
    } else {
      mapError.value = err?.response?.data?.message || err?.message || '地图加载失败'
    }
  } finally {
    if (isMapRequestCurrent(requestId)) loading.value = false
  }
}

async function showProvinceMap(provinceName) {
  const requestId = beginMapRequest()
  loading.value = true
  mapError.value = ''
  currentProvince.value = provinceName
  currentCity.value = ''
  mapScope.value = provinceName
  regionInsights.value = null
  emit('scope-change', { province: provinceName, city: '全部' })
  try {
    const adcode = PROVINCE_ADCODES[provinceName]
    const [geoJsonFull, mapData] = await Promise.all([
      loadGeoJson(adcode),
      fetchMapData(provinceName),
    ])
    if (!isMapRequestCurrent(requestId)) return
    const mapName = `province-${adcode}`
    const mainGeoJson = prepareGeoJson(adcode, geoJsonFull)
    echarts.registerMap(mapName, mainGeoJson)
    activeMapData = mapData
    mapMeta.value = mapData
    const mapOverrides = getProvinceMapLayoutOverrides(provinceName, adcode)
    if (!(await waitForChartContainer())) return
    renderMap({
      geoJson: mainGeoJson,
      fullGeoJson: geoJsonFull,
      adcode,
      mapName,
      regions: mapData.regions || [],
      scope: provinceName,
      maxRate: mapData.max_failure_rate,
      mapOverrides,
      onRegionClick: buildProvinceRegionClickHandler(provinceName, mapData),
    })
    void loadProvinceTrend(provinceName)
    await loadRegionInsights(provinceName, '全部')
  } catch (err) {
    if (!isMapRequestCurrent(requestId)) return
    mapError.value = err?.response?.data?.message || err?.message || '省级地图加载失败'
  } finally {
    if (isMapRequestCurrent(requestId)) loading.value = false
  }
}

function handleResize() {
  chart?.resize()
}

watch(
  () => props.dateRange,
  () => {
    if (!mapViewActive) return
    if (currentProvince.value) {
      void showProvinceMap(currentProvince.value)
    } else {
      void showChinaMap()
    }
  },
  { deep: true },
)

onActivated(async () => {
  chartAlive.value = true
  mapError.value = ''
  await nextTick()
  await reviveMapView()
})

onDeactivated(() => {
  reviveSerial += 1
  mapViewActive = false
  mapRequestId += 1
  disposeChart()
  chartAlive.value = false
})

onBeforeUnmount(() => {
  mapViewActive = false
  mapRequestId += 1
  disposeChart()
  chartAlive.value = false
})

async function refreshMap(targetProvince) {
  const prov = targetProvince !== undefined ? targetProvince : currentProvince.value
  if (prov && prov !== '全部' && prov !== '全国') {
    await showProvinceMap(prov)
  } else {
    await showChinaMap()
  }
}

defineExpose({ refresh: refreshMap, revive: reviveMapView })
</script>

<template>
  <div class="failure-rate-map">
    <div class="failure-rate-map__head">
      <div>
        <h4>不合格率地图</h4>
        <p class="page-hint">
          绿色表示不合格率较低、红色表示较高（可点击左侧颜色方块过滤显示对应区域）；点省份左侧看省内城市、右侧看全省榜单；点城市仅切换右侧该市榜单
        </p>
        <p v-if="mapHint" class="failure-rate-map__hint">{{ mapHint }}</p>
      </div>
      <div class="failure-rate-map__actions">
        <span class="failure-rate-map__scope">{{ mapScope }}</span>
        <el-button v-if="currentCity" size="small" @click="clearCitySelection">返回全省榜单</el-button>
        <el-button v-if="currentProvince" size="small" @click="showChinaMap">返回全国</el-button>
      </div>
    </div>

    <div
      v-loading="loading"
      class="failure-rate-map__body"
      :class="{ 'failure-rate-map__body--split': drillDownActive }"
    >
      <div v-if="chartAlive" class="failure-rate-map__chart-container" style="position: relative; height: 100%; min-width: 0;">
        <div ref="chartRef" class="failure-rate-map__chart" />
        
        <!-- 自定义 HTML 图例，实现白底 + 对应颜色边框 -->
        <div class="custom-legend">
          <div class="custom-legend__title">不合格率高</div>
          <div
            v-for="item in legendItems"
            :key="item.index"
            class="custom-legend__item"
            :class="{ 'custom-legend__item--inactive': !legendSelected[item.index] }"
            @click="toggleLegend(item.index)"
            title="点击过滤此区间数据"
          >
            <span
              class="custom-legend__color-box"
              :style="{
                backgroundColor: legendSelected[item.index] ? item.color : '#ffffff',
                borderColor: item.color,
              }"
            />
            <span class="custom-legend__label">{{ item.label }}</span>
          </div>
          <div class="custom-legend__title">不合格率低</div>
        </div>

        <!-- 区域趋势迷你图 (Sparkline Trend Card) -->
        <div v-if="currentProvince && trendData && trendData.length > 0" class="trend-mini-card">
          <div class="trend-mini-card__header">
            <span class="trend-mini-card__title">{{ currentProvince }}近 6 个月趋势</span>
            <span :class="['trend-badge', `trend-badge--${trendStatusClass}`]">{{ trendStatus }}</span>
          </div>
          
          <div class="trend-sparkline-container">
            <svg width="200" height="45" viewBox="0 0 200 45" style="overflow: visible;">
              <defs>
                <linearGradient :id="sparklineGradientId" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" :stop-color="sparklineColor" stop-opacity="0.25" />
                  <stop offset="100%" :stop-color="sparklineColor" stop-opacity="0.0" />
                </linearGradient>
              </defs>
              <path :d="areaPath" :fill="`url(#${sparklineGradientId})`" />
              <path :d="linePath" fill="none" :stroke="sparklineColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              <circle
                v-for="(pt, idx) in points"
                :key="idx"
                :cx="pt.x"
                :cy="pt.y"
                :r="hoveredPoint === idx ? 4.5 : 3"
                :fill="sparklineColor"
                stroke="#fff"
                :stroke-width="hoveredPoint === idx ? 2 : 1"
                @mouseenter="hoveredPoint = idx"
                @mouseleave="hoveredPoint = null"
                style="cursor: pointer; transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);"
              />
            </svg>
            <transition name="fade">
              <div
                v-if="hoveredPoint !== null && points[hoveredPoint]"
                class="sparkline-tooltip"
                :style="{
                  left: `${points[hoveredPoint].x}px`,
                  top: `${points[hoveredPoint].y - 32}px`
                }"
              >
                <span class="sparkline-tooltip__month">{{ points[hoveredPoint].data.month }}</span>
                <span class="sparkline-tooltip__rate">{{ points[hoveredPoint].data.failure_rate }}%</span>
              </div>
            </transition>
          </div>
          
          <div class="trend-mini-card__footer">
            <span>近6个月不合格率变化</span>
          </div>
        </div>
      </div>


      <CityInsightPanel
        v-if="drillDownActive"
        :key="`${currentProvince}_${currentCity || '全部'}`"
        :loading="regionInsightsLoading"
        :insights="regionInsights"
        :scope-label="insightScopeLabel"
        :province="currentProvince"
        :city="currentCity || '全部'"
        :date-range="props.dateRange"
        v-model:top-limit="regionTopLimit"
      />
      <el-empty v-if="mapError" :description="mapError">
        <el-button
          size="small"
          type="primary"
          @click="currentCity ? clearCitySelection() : currentProvince ? showProvinceMap(currentProvince) : showChinaMap()"
        >
          重试
        </el-button>
      </el-empty>
    </div>
  </div>
</template>

<style scoped>
.failure-rate-map {
  margin-top: 24px;
  border-top: 1px solid var(--app-border-light);
  padding-top: 20px;
}

.failure-rate-map__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.failure-rate-map__head h4 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
}

.failure-rate-map__hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--app-ratio-fail-text);
}

.failure-rate-map__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.failure-rate-map__scope {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(191, 219, 254, 0.45);
  color: var(--app-primary-dark);
  font-size: 12px;
  font-weight: 600;
  backdrop-filter: blur(8px);
}

.failure-rate-map__body {
  position: relative;
  min-height: 520px;
  border-radius: var(--app-radius-sm);
  background: linear-gradient(
    165deg,
    rgba(255, 255, 255, 0.72) 0%,
    rgba(240, 249, 255, 0.45) 45%,
    rgba(255, 241, 245, 0.35) 100%
  );
  border: 1px solid var(--app-glass-border);
  overflow: hidden;
  backdrop-filter: blur(12px);
}

.failure-rate-map__body--split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) min(420px, 38%);
  gap: 12px;
  padding: 12px;
  min-height: 400px;
}

.failure-rate-map__chart {
  width: 100%;
  height: 520px;
  cursor: grab;
  touch-action: none;
  border-radius: 10px;
}

/* 自定义图例样式：白底 + 原有颜色边框 */
.custom-legend {
  position: absolute;
  left: 16px;
  bottom: 16px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(191, 219, 254, 0.45);
  border-radius: var(--app-radius-sm);
  padding: 14px 18px;
  backdrop-filter: blur(8px);
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 10px;
  user-select: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.custom-legend__title {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.custom-legend__item {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.custom-legend__item:hover {
  transform: translateX(3px);
}

.custom-legend__color-box {
  width: 15px;
  height: 15px;
  border-radius: 4px;
  border-width: 2.5px;
  border-style: solid;
  box-sizing: border-box;
  transition: all 0.2s ease;
}

.custom-legend__label {
  font-size: 12.5px;
  color: #64748b;
  font-weight: 500;
  transition: color 0.2s ease;
}

.custom-legend__item--inactive .custom-legend__label {
  color: #cbd5e1;
  text-decoration: line-through;
  text-decoration-color: rgba(203, 213, 225, 0.6);
}



.failure-rate-map__body--split .failure-rate-map__chart {
  height: 100%;
  min-height: 400px;
  min-width: 0;
}

.failure-rate-map__chart:active {
  cursor: grabbing;
}

.failure-rate-map__body :deep(.el-empty) {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.82);
  z-index: 6;
}

@media (max-width: 960px) {
  .failure-rate-map__body--split {
    grid-template-columns: 1fr;
  }

  .failure-rate-map__body--split .failure-rate-map__chart {
    height: 360px;
  }
}

.failure-rate-map__chart-container {
  min-height: 520px;
}

.failure-rate-map__body--split .failure-rate-map__chart-container {
  min-height: 400px;
  height: 100%;
}

.trend-mini-card {
  position: absolute;
  right: 16px;
  bottom: 16px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(191, 219, 254, 0.45);
  border-radius: var(--app-radius-sm);
  padding: 10px 12px;
  backdrop-filter: blur(8px);
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 224px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  box-sizing: border-box;
}

.trend-mini-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 4px;
}

.trend-mini-card__title {
  font-size: 11px;
  font-weight: 600;
  color: var(--app-text);
}

.trend-badge {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
  white-space: nowrap;
}

.trend-badge--danger {
  background-color: #fee2e2;
  color: #ef4444;
}

.trend-badge--success {
  background-color: #d1fae5;
  color: #10b981;
}

.trend-badge--info {
  background-color: #e0f2fe;
  color: #0284c7;
}

.trend-sparkline-container {
  position: relative;
  width: 200px;
  height: 45px;
  margin-top: 4px;
}

.sparkline-tooltip {
  position: absolute;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.9);
  color: #fff;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 9px;
  pointer-events: none;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.1);
  white-space: nowrap;
}

.sparkline-tooltip::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  border-width: 4px 4px 0;
  border-style: solid;
  border-color: rgba(15, 23, 42, 0.9) transparent;
  display: block;
  width: 0;
}

.sparkline-tooltip__month {
  font-weight: 500;
  opacity: 0.8;
}

.sparkline-tooltip__rate {
  font-weight: 700;
  color: #38bdf8;
}

.trend-mini-card__footer {
  font-size: 9px;
  color: #94a3b8;
  border-top: 1px solid rgba(226, 232, 240, 0.5);
  padding-top: 4px;
  text-align: left;
}

/* fade transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
