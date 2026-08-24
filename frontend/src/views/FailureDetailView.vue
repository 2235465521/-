<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getData, openSourceFile } from '@/api'
import { buildDateQueryParams, displayReason, formatSourceLocation, normalizeFailureItemName, shouldMergeFailureItemToOther } from '@/utils/format'
import InfoChip from '@/components/InfoChip.vue'
import RatioBar from '@/components/RatioBar.vue'
import TablePager from '@/components/TablePager.vue'
import { useAnalytics } from '@/composables/useAnalytics'

defineOptions({ name: 'FailureDetailView' })

const route = useRoute()
const router = useRouter()
const filters = inject('filters')
const { formatSummary } = useAnalytics()

const mode = computed(() => (route.name === 'product-failures' ? 'product' : 'company'))
const company = computed(() => String(route.query.company || '').trim())
const product = computed(() => String(route.query.product || '').trim())
const entity = computed(() => (route.query.entity === 'manufacturer' ? 'manufacturer' : 'sampled'))
const entityLabel = computed(() => (entity.value === 'manufacturer' ? '食品生产单位' : '被抽检单位'))
const subjectLabel = computed(() => (mode.value === 'product' ? '产品' : entityLabel.value))
const subjectName = computed(() => (mode.value === 'product' ? product.value : company.value))

const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const items = ref([])
const loading = ref(false)
const loadedSnapshot = ref('')
const entityStats = ref(null)
const serverItemBreakdown = ref([])

const displayStats = computed(() => {
  if (entityStats.value) return entityStats.value
  return { total: total.value, unqualified: total.value, rate: null }
})

function snapshotKey() {
  return `${subjectKey()}|${filters.province}|${filters.city}|${JSON.stringify(filters.dateRange || null)}|p${page.value}|s${pageSize.value}`
}

const itemBreakdown = computed(() => {
  const counter = new Map()
  const source = serverItemBreakdown.value.length
    ? serverItemBreakdown.value.map(row => ({ name: row.item || row.name, count: row.count || 1 }))
    : items.value.map(row => ({ name: row.unqualified_item || '未知项目', count: 1 }))

  for (const entry of source) {
    const raw = (entry.name || '未知项目').trim() || '未知项目'
    const norm = normalizeFailureItemName(raw)
    if (shouldMergeFailureItemToOther(norm) || shouldMergeFailureItemToOther(raw)) continue
    counter.set(norm, (counter.get(norm) || 0) + Number(entry.count || 1))
  }

  return [...counter.entries()]
    .map(([item, count]) => ({ item, count }))
    .sort((a, b) => b.count - a.count)
})

function buildParams(extra = {}) {
  const params = {
    type: 'unqualified',
    province: filters.province,
    city: filters.city,
    page: page.value,
    page_size: pageSize.value,
    ...buildDateQueryParams(filters.dateRange),
    ...extra,
  }
  if (mode.value === 'product') {
    params.product = product.value
  } else {
    params.company = company.value
    params.entity_role = entity.value === 'manufacturer' ? 'manufacturer' : 'sampled'
  }
  return params
}

function subjectKey() {
  return `${mode.value}|${subjectName.value}|${entity.value}`
}

async function loadEntityStats() {
  const base = buildParams()
  const qualifiedParams = { ...base, type: 'qualified', page: 1, page_size: 1 }
  const [{ data: unqualifiedData }, { data: qualifiedData }] = await Promise.all([
    getData({ ...base, page: 1, page_size: 1 }),
    getData(qualifiedParams),
  ])
  const unqualified = unqualifiedData.total || 0
  const qualified = qualifiedData.total || 0
  const all = unqualified + qualified
  entityStats.value = {
    total: all,
    unqualified,
    rate: all > 0 ? Math.round((unqualified / all) * 10000) / 100 : null,
  }
  if (Array.isArray(unqualifiedData.item_breakdown) && unqualifiedData.item_breakdown.length) {
    serverItemBreakdown.value = unqualifiedData.item_breakdown
  }
}

async function loadData(force = false) {
  if (!subjectName.value) return
  const key = snapshotKey()
  if (!force && loadedSnapshot.value === key && items.value.length) return
  loading.value = true
  entityStats.value = null
  try {
    const [{ data }] = await Promise.all([
      getData(buildParams()),
      loadEntityStats(),
    ])
    items.value = data.items || []
    total.value = data.total || 0
    if (Array.isArray(data.item_breakdown) && data.item_breakdown.length) {
      serverItemBreakdown.value = data.item_breakdown
    }
    const serverPage = data.page || page.value
    if (serverPage !== page.value) page.value = serverPage
    loadedSnapshot.value = snapshotKey()
  } catch (err) {
    items.value = []
    total.value = 0
    entityStats.value = null
    serverItemBreakdown.value = []
    ElMessage.error(err?.response?.data?.message || err?.message || '加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function handleOpenFile(rowOrPath) {
  let path = typeof rowOrPath === 'object'
    ? (rowOrPath?.source_file || rowOrPath?.file_source || rowOrPath?.file_id)
    : rowOrPath
  if (!path) {
    ElMessage.error('无源文件路径')
    return
  }
  try {
    const { data } = await openSourceFile(path)
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
}

function goBack() {
  router.push({ name: mode.value === 'product' ? 'rank-product' : 'rank-unit' })
}

watch(
  () => [filters.province, filters.city, filters.dateRange, subjectName.value, entity.value, mode.value],
  () => {
    page.value = 1
    loadData()
  },
)

onMounted(() => {
  if (!subjectName.value) {
    ElMessage.warning(mode.value === 'product' ? '缺少产品名称' : '缺少单位名称')
    goBack()
    return
  }
  loadData()
})
</script>

<template>
  <div v-loading="loading" class="page-view page-stack unit-failure-page">
    <div class="unit-failure-page__toolbar">
      <el-button :icon="ArrowLeft" text @click="goBack">
        {{ mode === 'product' ? '返回产品榜单' : '返回红绿榜' }}
      </el-button>
      <InfoChip :text="formatSummary(filters.province, filters.city, filters.dateRange)" />
    </div>

    <el-card class="unit-failure-page__summary">
      <template #header>
        <div class="panel-card-header">
          <span>{{ subjectLabel }} · 不合格明细</span>
        </div>
      </template>
      <div class="unit-failure-page__headline">
        <h2>{{ subjectName }}</h2>
        <div v-if="displayStats.total || displayStats.unqualified" class="unit-failure-page__stats">
          <span>抽检总数 {{ displayStats.total }}</span>
          <span>不合格数 {{ displayStats.unqualified }}</span>
          <span v-if="displayStats.rate !== null" class="unit-failure-page__rate">
            不合格率 <RatioBar :ratio="displayStats.rate" />
          </span>
        </div>
      </div>
      <p class="page-hint">以下为当前筛选范围内的不合格抽检记录，含源文件链接，便于核查原始公告附件。</p>
    </el-card>

    <el-card v-if="itemBreakdown.length" class="unit-failure-page__breakdown">
      <template #header>
        <div class="panel-card-header">
          <span>不合格项目分布</span>
          <span class="panel-card-count">当前页 {{ itemBreakdown.length }} 项</span>
        </div>
      </template>
      <div class="unit-failure-page__tags">
        <el-tag
          v-for="row in itemBreakdown"
          :key="row.item"
          type="danger"
          effect="plain"
          size="small"
        >
          {{ row.item }}（{{ row.count }}）
        </el-tag>
      </div>
    </el-card>

    <el-card class="table-card table-card--glass">
      <template #header>
        <div class="panel-card-header">
          <span>不合格记录明细</span>
          <span class="panel-card-count">共 {{ total.toLocaleString() }} 条</span>
        </div>
      </template>
      <div class="glass-table-shell">
        <div v-loading="loading" class="glass-table-body">
          <el-table :data="items" stripe class="data-table-wrap data-table-wrap--in-shell">
            <el-table-column label="序号" width="70" class-name="col-rank" label-class-name="col-rank">
              <template #default="{ $index }">{{ (page - 1) * pageSize + $index + 1 }}</template>
            </el-table-column>
            <el-table-column prop="sampled_company" label="被抽检单位" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.sampled_company || row.company || '-' }}</template>
            </el-table-column>
            <el-table-column prop="product" label="产品名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="unqualified_item" label="不合格项目" min-width="140" show-overflow-tooltip />
            <el-table-column label="原因" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ displayReason(row) }}</template>
            </el-table-column>
            <el-table-column prop="manufacturer" label="生产单位" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.manufacturer || '-' }}</template>
            </el-table-column>
            <el-table-column label="抽样省市" min-width="120">
              <template #default="{ row }">{{ row.province_city || row.province || '-' }}</template>
            </el-table-column>
            <el-table-column label="数据省市" min-width="120">
              <template #default="{ row }">{{ formatSourceLocation(row) }}</template>
            </el-table-column>
            <el-table-column label="源文件" min-width="200">
              <template #default="{ row }">
                <el-link type="primary" @click="handleOpenFile(row)">
                  {{ row.source_file_name || '打开源文件' }}{{ row.source_sheet ? ` [${row.source_sheet}]` : '' }}
                </el-link>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="!loading && !items.length" class="list-empty">
            <el-empty description="暂无不合格记录" :image-size="88" />
          </div>
        </div>

        <TablePager
          v-if="total > 0 || items.length > 0"
          :current="page"
          :page-size="pageSize"
          :total="total"
          :loading="loading"
          :show-size-changer="true"
          :page-size-options="[50, 100, 200]"
          @page-change="handlePageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.unit-failure-page__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.unit-failure-page__headline h2 {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 700;
  color: var(--app-text);
}

.unit-failure-page__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.unit-failure-page__rate {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.unit-failure-page__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list-empty {
  padding: 12px 0 24px;
}
</style>
