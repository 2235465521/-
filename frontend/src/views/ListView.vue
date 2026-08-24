<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCompanyStats, getData, openSourceFile } from '@/api'
import { buildDateQueryParams, displayReason, formatSourceLocation } from '@/utils/format'
import RatioBar from '@/components/RatioBar.vue'
import TablePager from '@/components/TablePager.vue'
import { buildPageCacheKey, getListCache, hasListCache, isListPrefetching, markListPrefetching, setListCache, unmarkListPrefetching, getListPrefetchPromise } from '@/composables/useListDataCache'

defineOptions({ name: 'ListView' })

const route = useRoute()
const filters = inject('filters')

const listType = computed(() => route.meta.type || 'qualified')
const page = ref(1)
const pageSize = ref(30)
const total = ref(0)
const items = ref([])
const loading = ref(false)
const companyItems = ref([])

const search = computed(() => filters.search)

const hasActiveFilters = computed(() => {
  const s = search.value
  return Boolean(
    filters.province && filters.province !== '全部'
    || filters.city && filters.city !== '全部'
    || (filters.dateRange?.length === 2 && filters.dateRange[0] && filters.dateRange[1])
    || s.company?.trim()
    || s.product?.trim()
    || s.item?.trim()
    || s.category?.trim(),
  )
})

const emptyDescription = computed(() => {
  if (hasActiveFilters.value) {
    return '当前筛选条件下没有匹配记录'
  }
  return '还没有可展示的数据'
})

const emptyHint = computed(() => {
  if (hasActiveFilters.value) {
    return '试试放宽省市、时间范围，或清空上方搜索条件'
  }
  return '请确认数据库 shipin 已导入，或放宽筛选条件'
})

const columns = computed(() => {
  const companyCols = [
    { prop: 'sampled_company', label: '被抽检单位', minWidth: 160 },
    { prop: 'manufacturer', label: '生产单位', minWidth: 160 },
  ]
  if (listType.value === 'qualified') {
    return [
      { prop: 'index', label: '序号', width: 70 },
      ...companyCols,
      { prop: 'product', label: '原名', minWidth: 140 },
      { prop: 'province_city', label: '抽样省市', minWidth: 120 },
      { prop: 'sub_category', label: '小类', width: 100 },
      { prop: 'source', label: '数据省市', minWidth: 120 },
      { prop: 'file', label: '源文件', minWidth: 180 },
    ]
  }
  return [
    { prop: 'index', label: '序号', width: 70 },
    ...companyCols,
    { prop: 'product', label: '原名', minWidth: 140 },
    { prop: 'province_city', label: '抽样省市', minWidth: 120 },
    { prop: 'item', label: '不合格项目', minWidth: 140 },
    { prop: 'sub_category', label: '小类', width: 100 },
    { prop: 'source', label: '数据省市', minWidth: 120 },
    { prop: 'file', label: '源文件', minWidth: 180 },
  ]
})

function buildParams(extra = {}) {
  const params = {
    type: listType.value,
    province: filters.province,
    city: filters.city,
    page: page.value,
    page_size: pageSize.value,
    ...extra,
  }
  if (search.value.company) params.company = search.value.company
  if (search.value.product) params.product = search.value.product
  if (search.value.item) params.item = search.value.item
  if (search.value.category) params.category = search.value.category
  Object.assign(params, buildDateQueryParams(filters.dateRange))
  return params
}

function listCacheKey(targetPage = page.value, targetPageSize = pageSize.value) {
  return buildPageCacheKey(listType.value, buildParams({ page: targetPage, page_size: targetPageSize }), targetPage, targetPageSize)
}

function snapshotListCache() {
  return {
    items: items.value,
    total: total.value,
    page: page.value,
    pageSize: pageSize.value,
    companyItems: companyItems.value,
  }
}

function restoreFromCache(cached) {
  if (!cached) return false
  items.value = cached.items || []
  total.value = cached.total || 0
  page.value = cached.page || page.value
  pageSize.value = cached.pageSize || pageSize.value
  companyItems.value = cached.companyItems || []
  return items.value.length > 0 || total.value > 0
}

async function prefetchPage(targetPage) {
  const key = listCacheKey(targetPage)
  if (hasListCache(key) || isListPrefetching(key)) return
  if (targetPage < 1) return
  const totalPages = Math.max(Math.ceil(total.value / pageSize.value), 1)
  if (total.value > 0 && targetPage > totalPages) return

  const params = buildParams({
    page: targetPage,
  })
  const promise = getData(params).then(({ data }) => {
    setListCache(key, {
      items: data.items || [],
      total: data.total ?? 0,
      page: targetPage,
      pageSize: pageSize.value,
      companyItems: companyItems.value,
    })
  })
  markListPrefetching(key, promise)
  try {
    await promise
  } catch {
    // 预加载失败不影响当前页展示
  } finally {
    unmarkListPrefetching(key)
  }
}

function schedulePrefetch() {
  if (total.value <= 0) return
  const totalPages = Math.max(Math.ceil(total.value / pageSize.value), 1)
  if (page.value < totalPages) void prefetchPage(page.value + 1)
  if (page.value > 1) void prefetchPage(page.value - 1)
}

async function loadData(force = false) {
  const key = listCacheKey()
  if (!force) {
    const cached = getListCache(key)
    if (restoreFromCache(cached)) {
      schedulePrefetch()
      return
    }
    const prefetchPromise = getListPrefetchPromise(key)
    if (prefetchPromise) {
      loading.value = true
      try {
        await prefetchPromise
        const newCached = getListCache(key)
        if (restoreFromCache(newCached)) {
          schedulePrefetch()
          return
        }
      } catch {
        // 预加载失败则降级进行普通请求
      } finally {
        loading.value = false
      }
    }
  }

  loading.value = true
  try {
    const { data } = await getData(buildParams())
    items.value = data.items || []
    total.value = data.total ?? 0
    const serverPage = data.page || page.value
    if (serverPage !== page.value) page.value = serverPage
    setListCache(key, snapshotListCache())
    schedulePrefetch()
  } catch (err) {
    items.value = []
    total.value = 0
    ElMessage.error(err?.response?.data?.message || err?.message || '加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function loadCompanyStats() {
  const kw = search.value.company?.trim()
  if (!kw) {
    companyItems.value = []
    return
  }
  const { data } = await getCompanyStats(kw, filters.province, filters.city, filters.dateRange)
  companyItems.value = data.items || []
}

async function handleOpenFile(rowOrPath) {
  let path = typeof rowOrPath === 'object'
    ? (rowOrPath?.file_id || rowOrPath?.source_file || rowOrPath?.file_source)
    : rowOrPath
  if (!path) {
    ElMessage.error('无源文件路径')
    return
  }
  try {
    const { data } = await openSourceFile(String(path))
    if (data.ok && data.mode === 'download' && data.url) {
      window.open(data.url, '_blank')
      ElMessage.success('正在下载源文件')
      return
    }
    if (data.ok) {
      ElMessage.success('已打开源文件')
      return
    }
    ElMessage.error(data.message || '无法打开文件')
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '无法打开文件')
  }
}

function handlePageChange(nextPage, nextPageSize = pageSize.value) {
  if (nextPageSize !== pageSize.value) {
    pageSize.value = nextPageSize
    page.value = 1
  } else {
    page.value = nextPage
  }
  loadData()
  const scrollEl = document.querySelector('.main-content-scroll')
  if (scrollEl) {
    scrollEl.scrollTop = 0
  }
}

watch(
  () => [filters.province, filters.city, filters.dateRange, listType.value],
  () => {
    page.value = 1
    loadData()
    loadCompanyStats()
  },
)

watch(
  () => ({ ...search.value }),
  () => {
    page.value = 1
    clearTimeout(window.__listSearchTimer)
    window.__listSearchTimer = setTimeout(() => {
      loadData()
      loadCompanyStats()
    }, 300)
  },
  { deep: true },
)

onMounted(() => {
  loadData()
  loadCompanyStats()
})

defineExpose({
  refresh: (force = false) => loadData(force),
  exportCsv: async () => {
    try {
      ElMessage.info('正在拉取数据准备导出，请稍候...')
      const params = buildParams({ page: 1, page_size: 500 })
      const { data: first } = await getData(params)
      let all = first.items || []
      const totalPages = first.total_pages || 1

      if (totalPages > 1) {
        const pagePromises = []
        for (let p = 2; p <= totalPages; p++) {
          pagePromises.push(getData({ ...params, page: p }))
        }
        const results = await Promise.all(pagePromises)
        for (const res of results) {
          if (res?.data?.items) {
            all = all.concat(res.data.items)
          }
        }
      }

      if (all.length === 0) {
        ElMessage.warning('当前筛选条件下暂无可导出的数据')
        return
      }

      const headers =
        listType.value === 'qualified'
          ? ['被抽检单位', '生产单位', '产品名称', '抽样省市', '小类', '数据省市', '源文件', '工作表']
          : ['被抽检单位', '生产单位', '产品名称', '抽样省市', '不合格项目', '小类', '数据省市', '源文件', '工作表']
      const lines = [headers.join(',')]
      for (const item of all) {
        const srcLoc = formatSourceLocation(item)
        const sampled = item.sampled_company || item.company || ''
        const manufacturer = item.manufacturer || ''
        const row =
          listType.value === 'qualified'
            ? [sampled, manufacturer, item.product, item.province_city || item.province, item.sub_category, srcLoc, item.source_file, item.source_sheet]
            : [sampled, manufacturer, item.product, item.province_city || item.province, item.unqualified_item, item.sub_category, srcLoc, item.source_file, item.source_sheet]
        lines.push(row.map((v) => `"${String(v || '').replace(/"/g, '""')}"`).join(','))
      }
      const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = listType.value === 'qualified' ? '合格汇总.csv' : '不合格汇总.csv'
      a.click()
      URL.revokeObjectURL(a.href)
      ElMessage.success(`导出成功，共导出 ${all.length} 条数据`)
    } catch (err) {
      console.error('导出 CSV 失败:', err)
      ElMessage.error('导出 CSV 失败：' + (err?.message || '网络连接或请求异常'))
      throw err
    }
  },
})
</script>

<template>
  <div class="page-view page-stack">
    <el-card v-if="companyItems.length" class="table-card">
      <template #header>
        <div class="panel-card-header">
          <span>单位抽检汇总</span>
          <span class="panel-card-count">{{ companyItems.length }} 家</span>
        </div>
      </template>
      <el-table :data="companyItems" size="small" stripe class="data-table-wrap">
        <el-table-column prop="company" label="单位名称" min-width="160" />
        <el-table-column prop="total_count" label="抽检总数" width="100" class-name="col-num" label-class-name="col-num" />
        <el-table-column prop="qualified_count" label="合格数" width="90" class-name="col-num" label-class-name="col-num" />
        <el-table-column prop="unqualified_count" label="不合格数" width="100" class-name="col-num" label-class-name="col-num" />
        <el-table-column label="不合格率" width="160">
          <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
        </el-table-column>
        <el-table-column label="涉及城市" min-width="160">
          <template #default="{ row }">{{ (row.cities || []).join('、') || '-' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="table-card table-card--glass">
      <template #header>
        <div class="panel-card-header">
          <span>{{ listType === 'qualified' ? '合格批次明细' : '不合格批次明细' }}</span>
          <span class="panel-card-count">共 {{ total.toLocaleString() }} 条</span>
        </div>
      </template>
      <div class="glass-table-shell">
        <div v-loading="loading" element-loading-text="数据较多、请耐心等候…" class="glass-table-body">
          <el-table
            :data="items"
            stripe
            :tooltip-options="{ placement: 'bottom-start', fallbackPlacements: ['bottom-start', 'bottom', 'top-start', 'top'] }"
            class="data-table-wrap data-table-wrap--in-shell"
          >
            <el-table-column label="序号" width="70" class-name="col-rank" label-class-name="col-rank">
              <template #default="{ $index }">{{ (page - 1) * pageSize + $index + 1 }}</template>
            </el-table-column>
            <el-table-column prop="sampled_company" label="被抽检单位" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.sampled_company || row.company || '-' }}</template>
            </el-table-column>
            <el-table-column prop="manufacturer" label="生产单位" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.manufacturer || '-' }}</template>
            </el-table-column>
            <el-table-column prop="product" label="原名" min-width="140" show-overflow-tooltip />
            <el-table-column label="抽样省市" min-width="120">
              <template #default="{ row }">{{ row.province_city || row.province || '-' }}</template>
            </el-table-column>
            <el-table-column v-if="listType === 'unqualified'" prop="unqualified_item" label="不合格项目" min-width="140" show-overflow-tooltip />
            <el-table-column prop="sub_category" label="小类" width="100" show-overflow-tooltip />
            <el-table-column label="数据省市" min-width="120">
              <template #default="{ row }">{{ formatSourceLocation(row) }}</template>
            </el-table-column>
            <el-table-column label="源文件" min-width="180">
              <template #default="{ row }">
                <el-link type="primary" @click="handleOpenFile(row)">
                  {{ row.source_file_name || '打开源文件' }}{{ row.source_sheet ? ` [${row.source_sheet}]` : '' }}
                </el-link>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="!loading && !items.length" class="list-empty">
            <el-empty :description="emptyDescription" :image-size="88">
              <p class="list-empty__hint">{{ emptyHint }}</p>
            </el-empty>
          </div>
        </div>

        <TablePager
          v-if="total > 0 || items.length > 0"
          :current="page"
          :page-size="pageSize"
          :total="total"
          :loading="loading"
          :show-size-changer="true"
          :page-size-options="[30, 50, 100]"
          @page-change="handlePageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.list-empty {
  padding: 12px 0 24px;
}

.list-empty__hint {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--app-text-muted);
  line-height: 1.5;
  max-width: 360px;
}
</style>
