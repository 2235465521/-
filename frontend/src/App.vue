<script setup>
import { computed, nextTick, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppSidebar from '@/components/AppSidebar.vue'
import AppHeader from '@/components/AppHeader.vue'
import FilterPanel from '@/components/FilterPanel.vue'
import { useScanStatus } from '@/composables/useScanStatus'
import { useAnalytics } from '@/composables/useAnalytics'
import { useAppData } from '@/composables/useAppData'
import { useOverview } from '@/composables/useOverview'
import { markDailyRefreshDone, markForceRefreshDone, shouldRunDailyRefresh } from '@/composables/useDailyRefresh'
import { clearListCache } from '@/composables/useListDataCache'
import { KEEP_ALIVE_VIEWS } from '@/constants/keepAliveViews'

const route = useRoute()
const viewRef = ref(null)
const exporting = ref(false)
const SIDEBAR_COLLAPSED_KEY = 'sidebar_collapsed'
const sidebarCollapsed = ref(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1')

function applySidebarCollapsed(collapsed) {
  document.documentElement.classList.toggle('sidebar-collapsed', collapsed)
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

watch(sidebarCollapsed, (collapsed) => {
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0')
  applySidebarCollapsed(collapsed)
})

const routeFiltersMap = reactive({})

function getDefaultFilterState() {
  return {
    province: '全部',
    city: '全部',
    dateRange: null,
    search: { company: '', product: '', item: '', category: '' },
  }
}

function getFilterStateForRoute(routeName) {
  if (!routeName) return getDefaultFilterState()
  if (!routeFiltersMap[routeName]) {
    routeFiltersMap[routeName] = getDefaultFilterState()
  }
  return routeFiltersMap[routeName]
}

const filters = reactive(getDefaultFilterState())
provide('filters', filters)

watch(
  () => route.name,
  (newRoute, oldRoute) => {
    if (oldRoute) {
      routeFiltersMap[oldRoute] = {
        province: filters.province,
        city: filters.city,
        dateRange: filters.dateRange ? [...filters.dateRange] : null,
        search: { ...filters.search },
      }
    }
    if (newRoute) {
      const targetState = getFilterStateForRoute(newRoute)
      filters.province = targetState.province
      filters.city = targetState.city
      filters.dateRange = targetState.dateRange ? [...targetState.dateRange] : null
      filters.search = { ...targetState.search }
      ensureCities(filters.province)
    }
  },
  { immediate: true },
)

const {
  provinces,
  citiesByProvince,
  ensureProvinces,
  ensureCities,
  apiError,
  invalidate: invalidateAppData,
} = useAppData()
const { invalidate: invalidateAnalytics } = useAnalytics()

const cities = computed(() => citiesByProvince.value[filters.province] || [])

const showToolbar = computed(() =>
  ['qualified', 'unqualified', 'rank-product', 'rank-unit', 'unit-failures', 'product-failures', 'rank', 'distribution', 'alert', 'greenlist'].includes(route.name),
)

const showSearch = computed(() => route.name === 'qualified' || route.name === 'unqualified')

const statusText = computed(() => {
  const s = status.value
  if (s.module_loading || s.cache_loading) return '后端正在加载模块与数据，请稍候…'
  if (s.running) return s.message || '正在扫描数据文件…'
  if (s.pending_checking) return '数据已就绪，正在后台检查是否有新文件'
  if (s.finished_at) {
    let msg = `数据更新于 ${s.finished_at}`
    if (s.pending_new > 0) msg += `，另有 ${s.pending_new} 个新文件待扫描`
    else if (s.auto_scan_enabled) msg += '，后台每日自动检查新文件'
    return msg
  }
  if (s.has_cache) return '已加载历史数据，可随时查看统计'
  return '首次使用请先点击左侧「重新扫描数据」'
})

const scanPercent = computed(() => {
  const s = status.value
  if (!s.total) return 0
  return Math.round(((s.progress || 0) / s.total) * 100)
})

const isScanning = computed(() => status.value.running || status.value.pending_checking)

const { invalidate: invalidateOverview } = useOverview()

async function reloadAllData(force = false) {
  if (force) clearListCache()
  invalidateAnalytics()
  invalidateAppData()
  invalidateOverview()
  await ensureProvinces(true)
  await ensureCities(filters.province, true)
  await viewRef.value?.refresh?.(force)
}

async function onManualScanComplete() {
  markForceRefreshDone()
  await reloadAllData(true)
}

const { status, triggerScan } = useScanStatus(onManualScanComplete)

async function applyDailyRefreshIfDue() {
  if (!shouldRunDailyRefresh()) return
  markDailyRefreshDone()
  await reloadAllData(true)
}

onMounted(async () => {
  applySidebarCollapsed(sidebarCollapsed.value)
  await nextTick()
  setTimeout(() => {
    applyDailyRefreshIfDue()
  }, 400)
})

async function onProvinceChange() {
  filters.city = '全部'
  await ensureCities(filters.province)
}

async function onCityChange() {
  // 筛选变化由子页面按 cache key 自行拉取，无需清空 analytics 缓存
}

function onDateChange() {
  // 同上
}

function clearSearch() {
  filters.search = { company: '', product: '', item: '', category: '' }
}

async function clearScope() {
  filters.province = '全部'
  filters.city = '全部'
  filters.dateRange = null
  await ensureCities('全部')
}

async function handleExport() {
  if (exporting.value) return
  if (!viewRef.value?.exportCsv) {
    ElMessage.warning('当前页面不支持数据导出')
    return
  }
  exporting.value = true
  try {
    await viewRef.value.exportCsv()
  } catch (e) {
    // 错误在组件内部处理与展示 Message
  } finally {
    exporting.value = false
  }
}

ensureProvinces()
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :collapsed="sidebarCollapsed"
      :scanning="status.running"
      :exporting="exporting"
      @toggle="toggleSidebar"
      @scan="triggerScan"
      @export="handleExport"
    />

    <div class="layout-main">
      <AppHeader
        :status-text="apiError ? '后端服务未就绪' : statusText"
        :is-scanning="isScanning"
        :scan-percent="scanPercent"
        :running="status.running"
        :backend-offline="Boolean(apiError)"
      />

      <div class="main-content-scroll">
        <div class="page-content">
          <el-alert
            v-if="apiError"
            type="error"
            :closable="false"
            show-icon
          >
            <template #title>{{ apiError }}</template>
            <p class="backend-offline-hint">
              请确认后端服务已启动并可访问 <code>/api/health</code>，然后按 Ctrl+F5 刷新本页。
            </p>
          </el-alert>

          <FilterPanel
            v-model:province="filters.province"
            v-model:city="filters.city"
            v-model:date-range="filters.dateRange"
            v-model:search="filters.search"
            :provinces="provinces"
            :cities="cities"
            :show-scope="showToolbar"
            :show-search="showSearch"
            @province-change="onProvinceChange"
            @city-change="onCityChange"
            @date-change="onDateChange"
            @clear-search="clearSearch"
            @clear-scope="clearScope"
          />

          <router-view v-slot="{ Component }">
            <keep-alive :include="KEEP_ALIVE_VIEWS" :max="12">
              <component :is="Component" :key="route.name" ref="viewRef" />
            </keep-alive>
          </router-view>
        </div>
      </div>
      <el-backtop target=".main-content-scroll" />
    </div>
  </div>
</template>

<style scoped>
.backend-offline-hint {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.backend-offline-hint code {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.06);
}
</style>
