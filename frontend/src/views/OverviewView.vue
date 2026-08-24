<script setup>
import { computed, nextTick, onActivated, onMounted, ref, watch } from 'vue'
import FailureRateMap from '@/components/FailureRateMap.vue'
import ItemTypePieChart from '@/components/ItemTypePieChart.vue'
import { useAppData } from '@/composables/useAppData'
import { useOverview } from '@/composables/useOverview'
import { dateRangePickerShortcuts, disabledFutureDate } from '@/utils/dateRangePicker'

defineOptions({ name: 'OverviewView' })

const { stats, ensureProvinces, ensureStats, ensureCities } = useAppData()
const { chart, loading: chartLoading, indexBuilding, loadChart } = useOverview()

const statsView = computed(() => stats.value || {})
const loadError = ref(false)

const provinces = ref([])
const cities = ref([])
const overviewProvince = ref('全部')
const overviewCity = ref('全部')
const overviewDateRange = ref(null)
const applied = ref({ province: '全部', city: '全部', dateRange: null })
const mapRef = ref(null)
const overviewReady = ref(false)

watch(overviewDateRange, (newVal) => {
  if (!newVal || newVal.length === 0) {
    overviewProvince.value = '全部'
    overviewCity.value = '全部'
    applyChart()
  }
})

const qualifiedRatio = computed(() => {
  const total = chart.value?.total_count || 0
  if (!total) return 0
  return ((chart.value?.qualified_count || 0) / total) * 100
})

const unqualifiedRatio = computed(() => {
  const total = chart.value?.total_count || 0
  if (!total) return 0
  return ((chart.value?.unqualified_count || 0) / total) * 100
})

const sortedCategories = computed(() => {
  const list = [...(chart.value?.categories || [])]
  return list.sort((a, b) => {
    const rateA = a.failure_rate ?? a.unqualified_ratio ?? 0
    const rateB = b.failure_rate ?? b.unqualified_ratio ?? 0
    if (rateB !== rateA) return rateB - rateA
    return (b.total_count || 0) - (a.total_count || 0)
  })
})

const unqualifiedCategoryItems = computed(() => chart.value?.unqualified_categories || [])

const unqualifiedCategoryTotal = computed(() => chart.value?.unqualified_count || 0)

const unqualifiedCategoryHint = computed(() => {
  const uncategorized = chart.value?.unqualified_uncategorized_count || 0
  const base = '占比为占全部不合格项次的比例；仅统计已映射小类。'
  if (!uncategorized) return `${base}其余小类已并入「其他」。`
  return `${base}未映射品名 ${uncategorized.toLocaleString()} 项次未纳入统计，其余小类已并入「其他」。`
})

const dateHint = computed(() => {
  const range = applied.value.dateRange
  if (!range?.[0] || !range?.[1]) return '时间范围：全部年份'
  return `时间范围：${range[0]} 至 ${range[1]}（按公告文件夹年份筛选）`
})

const fileHint = computed(() => {
  const s = stats.value || {}
  let hint = `共 ${s.total_files || 0} 个文件，${s.parsed_files || 0} 个含有效数据`
  if (s.date_filtered) hint = `时间段内 ${s.parsed_files || 0} 个文件含有效数据 / 全库 ${s.total_files || 0} 个`
  const skipped = (s.skipped_planned_files || 0) + (s.skipped_non_detail_files || s.skipped_non_detail || 0)
  if (skipped) {
    const parts = []
    if (s.skipped_planned_files) parts.push(`${s.skipped_planned_files} 个计划清单`)
    if (s.skipped_non_detail_files || s.skipped_non_detail) {
      parts.push(`${s.skipped_non_detail_files || s.skipped_non_detail} 个非明细附件`)
    }
    hint += `（另有 ${parts.join('、')}未纳入统计）`
  }
  if (s.pending_new > 0) hint += `；待自动扫描新文件 ${s.pending_new} 个`
  if (s.scanned_at) hint += `（数据时间：${s.scanned_at}）`
  return hint
})

const canApply = computed(() => {
  const dateChanged =
    JSON.stringify(overviewDateRange.value || null) !== JSON.stringify(applied.value.dateRange || null)
  return (
    overviewProvince.value !== applied.value.province ||
    overviewCity.value !== applied.value.city ||
    dateChanged
  )
})

async function loadOverviewProvinces() {
  const data = await ensureProvinces()
  provinces.value = data || []
  overviewProvince.value = applied.value.province
}

async function loadOverviewCities() {
  const data = await ensureCities(overviewProvince.value)
  cities.value = data || []
  if (
    overviewProvince.value === applied.value.province &&
    Array.isArray(cities.value) &&
    cities.value.includes(applied.value.city)
  ) {
    overviewCity.value = applied.value.city
  } else {
    overviewCity.value = '全部'
  }
}

async function applyChart() {
  applied.value = {
    province: overviewProvince.value,
    city: overviewCity.value,
    dateRange: overviewDateRange.value ? [...overviewDateRange.value] : null,
  }
  await loadAll(true)
}

async function handleMapScopeChange({ province, city }) {
  overviewProvince.value = province
  applied.value.province = province
  applied.value.city = city
  await loadOverviewCities()
  overviewCity.value = city
  
  loadError.value = false
  try {
    await loadChart(province, city, false, applied.value.dateRange)
  } catch {
    loadError.value = true
  }
}

async function loadAll(force = false) {
  if (!force && overviewReady.value && chart.value && stats.value?.count_mode === 'item') return
  loadError.value = false
  try {
    const dateRange = applied.value.dateRange
    const statsPromise = ensureStats(force, dateRange)
    const provincesPromise = loadOverviewProvinces()
    await statsPromise
    await loadChart(applied.value.province, applied.value.city, force, dateRange)
    provincesPromise.catch(() => {})
    loadOverviewCities().catch(() => {})
    if (force) {
      await mapRef.value?.refresh?.(applied.value.province)
    }
    overviewReady.value = Boolean(chart.value && stats.value?.count_mode === 'item')
  } catch {
    loadError.value = true
  }
}

onMounted(() => loadAll(false))

onActivated(async () => {
  await nextTick()
  mapRef.value?.revive?.()
})

defineExpose({ refresh: (force = false) => loadAll(force) })
</script>

<template>
  <div class="page-view overview-page page-stack">
    <div class="overview-toolbar glass-card">
      <div class="overview-toolbar__field">
        <span class="overview-toolbar__label">时间范围</span>
        <el-date-picker
          v-model="overviewDateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          unlink-panels
          clearable
          :disabled-date="disabledFutureDate"
          :shortcuts="dateRangePickerShortcuts"
          class="overview-toolbar__date"
        />
      </div>
      <p class="overview-toolbar__hint">{{ dateHint }}</p>
      <el-button type="primary" :disabled="!canApply" :loading="chartLoading" @click="applyChart">
        应用筛选
      </el-button>
    </div>

    <el-alert
      v-if="loadError"
      title="暂时无法加载数据"
      type="error"
      :closable="false"
      class="page-summary"
    >
      <p class="overview-error-hint">请确认后端服务已启动，然后重试</p>
      <el-button size="small" type="primary" @click="loadAll(true)">重新加载</el-button>
    </el-alert>

    <div class="stat-strip glass-card">
      <div class="stat-item stat-item--qualified">
        <span class="stat-item__label">合格项次</span>
        <span class="stat-item__value">{{ (statsView.qualified_count || 0).toLocaleString() }}</span>
      </div>
      <div class="stat-item stat-item--unqualified">
        <span class="stat-item__label">不合格项次</span>
        <span class="stat-item__value">{{ (statsView.unqualified_count || 0).toLocaleString() }}</span>
      </div>
      <div class="stat-item stat-item--files">
        <span class="stat-item__label">有效数据文件</span>
        <span class="stat-item__value">{{ statsView.parsed_files || 0 }}/{{ statsView.total_files || 0 }}</span>
        <span class="stat-item__hint" :title="fileHint">{{ fileHint }}</span>
      </div>
      <div class="stat-item stat-item--provinces">
        <span class="stat-item__label">覆盖省份</span>
        <span class="stat-item__value">{{ Object.keys(statsView.provinces || {}).length }}</span>
      </div>
    </div>

    <el-card class="chart-panel map-panel">
      <FailureRateMap ref="mapRef" :date-range="applied.dateRange" @scope-change="handleMapScopeChange" />
    </el-card>

    <el-card v-loading="chartLoading" class="chart-panel">
      <template #header>
        <div class="chart-header">
          <span>范围统计</span>
          <div class="chart-filters">
            <el-select v-model="overviewProvince" style="width: 140px" @change="loadOverviewCities(); overviewCity = '全部'">
              <el-option label="全部省份" value="全部" />
              <el-option v-for="p in provinces" :key="p" :label="p" :value="p" />
            </el-select>
            <el-select v-model="overviewCity" style="width: 140px">
              <el-option label="全部城市" value="全部" />
              <el-option v-for="c in cities" :key="c" :label="c" :value="c" />
            </el-select>
            <el-button type="primary" :disabled="!canApply" :loading="chartLoading" @click="applyChart">确定</el-button>
          </div>
        </div>
      </template>

      <div v-if="chartLoading || indexBuilding" class="overview-building">
        <p>{{ indexBuilding ? '范围统计索引计算中，首次启动约需 15–20 秒…' : '正在加载范围统计…' }}</p>
      </div>

      <template v-else-if="chart?.total_count">
        <div class="ratio-summary">
          <div class="ratio-summary__head">
            <span class="scope">{{ chart.scope || '全国' }}</span>
            <span class="ratio-summary__total">
              合计 {{ chart.total_count.toLocaleString() }} 项 · 不合格率 {{ chart.failure_rate || 0 }}%
            </span>
          </div>
          <div class="ratio-bar">
            <div class="ratio-bar__q" :style="{ width: qualifiedRatio + '%' }" />
            <div class="ratio-bar__u" :style="{ width: unqualifiedRatio + '%' }" />
          </div>
          <div class="ratio-legend">
            <span class="ratio-legend__item q">
              合格 {{ (chart.qualified_count || 0).toLocaleString() }}（{{ qualifiedRatio.toFixed(2) }}%）
            </span>
            <span class="ratio-legend__item u">
              不合格 {{ (chart.unqualified_count || 0).toLocaleString() }}（{{ unqualifiedRatio.toFixed(2) }}%）
            </span>
          </div>
        </div>

        <div v-if="unqualifiedCategoryItems.length" class="category-panel category-panel--pie">
          <h4>不合格食品小类占比</h4>
          <p class="page-hint category-panel-hint">{{ unqualifiedCategoryHint }}</p>
          <ItemTypePieChart
            :items="unqualifiedCategoryItems"
            :grand-total="unqualifiedCategoryTotal"
            center-label="不合格项次"
            count-unit="项"
            :max-slices="13"
          />
        </div>

        <div v-if="sortedCategories.length" class="category-panel">
          <h4>各类食品小类占比</h4>
          <p class="page-hint category-panel-hint">按不合格率从高到低；至少 100 项才显示</p>
          <div v-for="item in sortedCategories" :key="item.category" class="cat-row">
            <div class="cat-label" :title="item.category">{{ item.category }}</div>
            <div class="cat-track">
              <div class="seg q" :style="{ width: item.qualified_ratio + '%' }" />
              <div class="seg u" :style="{ width: item.unqualified_ratio + '%' }" />
            </div>
            <div class="cat-meta"><span class="q">{{ item.qualified_ratio }}%</span> / <span class="u">{{ item.unqualified_ratio }}%</span></div>
            <div class="cat-count">{{ item.total_count.toLocaleString() }}</div>
          </div>
        </div>
      </template>
      <el-empty v-else description="当前范围暂无数据">
        <el-button type="primary" size="small" @click="loadAll(true)">重新加载</el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<style scoped>
.overview-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 16px;
  margin-bottom: 12px;
}

.overview-toolbar__field {
  display: flex;
  align-items: center;
  gap: 10px;
}

.overview-toolbar__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-secondary);
  white-space: nowrap;
}

.overview-toolbar__date {
  width: 280px;
}

.overview-toolbar__hint {
  flex: 1;
  min-width: 220px;
  margin: 0;
  font-size: 12px;
  color: var(--app-text-muted);
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  padding: 0;
  overflow: hidden;
  min-width: 0;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 18px;
  border-right: 1px solid rgba(226, 232, 240, 0.7);
  min-width: 0;
  position: relative;
  transition: background 0.2s ease;
}

.stat-item:hover {
  background: rgba(255, 255, 255, 0.45);
}

.stat-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  opacity: 0.85;
}

.stat-item--qualified::before { background: var(--app-qualified); }
.stat-item--unqualified::before { background: var(--app-unqualified); }
.stat-item--files::before { background: var(--app-accent-files); }
.stat-item--provinces::before { background: var(--app-success); }

.stat-item:last-child {
  border-right: none;
}

.stat-item__label {
  font-size: 12px;
  color: var(--app-text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.stat-item__value {
  font-family: var(--app-font-headline);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.stat-item__hint {
  font-size: 11px;
  color: var(--app-text-muted);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-item--qualified .stat-item__value { color: var(--app-qualified); }
.stat-item--unqualified .stat-item__value { color: var(--app-unqualified); }
.stat-item--files .stat-item__value { color: var(--app-accent-files); font-size: 20px; }
.stat-item--provinces .stat-item__value { color: var(--app-success); }

/* 仅在窗口明显小于布局最小宽度时降级，避免随意缩放时频繁跳变 */
@media (max-width: 1199px) {
  .stat-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stat-item:nth-child(2) {
    border-right: none;
  }

  .stat-item:nth-child(1),
  .stat-item:nth-child(2) {
    border-bottom: 1px solid rgba(226, 232, 240, 0.7);
  }
}

.chart-panel {
  box-shadow: var(--app-shadow) !important;
  --ratio-pass: var(--app-ratio-pass);
  --ratio-pass-light: var(--app-ratio-pass-end);
  --ratio-fail: var(--app-ratio-fail);
  --ratio-fail-light: var(--app-ratio-fail-end);
  --ratio-pass-text: var(--app-ratio-pass-text);
  --ratio-fail-text: var(--app-ratio-fail-text);
  --ratio-track: var(--app-ratio-track);
}

.map-panel :deep(.el-card__body) {
  padding-top: 8px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.chart-filters {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.scope {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid rgba(191, 219, 254, 0.45);
  backdrop-filter: blur(8px);
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-secondary);
}

.ratio-summary__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.ratio-summary__total {
  font-size: 13px;
  color: var(--app-text-secondary);
}

.ratio-bar {
  display: flex;
  height: 14px;
  background: var(--ratio-track);
  border-radius: 999px;
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.06);
}

.ratio-bar__q {
  background: linear-gradient(90deg, var(--ratio-pass), var(--ratio-pass-light));
  min-width: 2px;
  transition: width 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}

.ratio-bar__u {
  background: linear-gradient(90deg, var(--ratio-fail), var(--ratio-fail-light));
  min-width: 2px;
  transition: width 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}

.ratio-legend {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 12px;
  font-size: 13px;
}

.ratio-legend__item.q { color: var(--ratio-pass-text); font-weight: 600; }
.ratio-legend__item.u { color: var(--ratio-fail-text); font-weight: 600; }

.category-panel {
  margin-top: 24px;
  border-top: 1px solid var(--app-border-light);
  padding-top: 20px;
}

.category-panel--pie {
  padding-bottom: 8px;
}

.category-panel h4 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
}

.category-panel-hint {
  margin: 0 0 12px;
}

.cat-row {
  display: grid;
  grid-template-columns: minmax(80px, 120px) minmax(0, 1fr) minmax(72px, 90px) minmax(52px, 60px);
  gap: 10px;
  align-items: center;
  min-width: 0;
  margin-bottom: 6px;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: var(--app-radius-xs);
  transition: background 0.18s ease;
}

.cat-row:hover {
  background: rgba(248, 250, 252, 0.85);
}

.cat-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-secondary);
  font-weight: 500;
}

.cat-track {
  display: flex;
  height: 10px;
  background: var(--ratio-track);
  border-radius: 999px;
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.05);
}

.seg.q {
  background: linear-gradient(90deg, var(--ratio-pass), var(--ratio-pass-light));
  transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

.seg.u {
  background: linear-gradient(90deg, var(--ratio-fail), var(--ratio-fail-light));
  transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

.cat-meta {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cat-meta .q { color: var(--ratio-pass-text); font-weight: 600; }
.cat-meta .u { color: var(--ratio-fail-text); font-weight: 600; }

.cat-count {
  text-align: right;
  color: var(--app-text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.overview-error-hint {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--app-text-secondary);
  line-height: 1.5;
}

.overview-building {
  padding: 48px 16px;
  text-align: center;
  color: var(--app-text-secondary);
  font-size: 14px;
  line-height: 1.6;
}
</style>
