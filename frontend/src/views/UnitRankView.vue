<script setup>
import { computed, inject, nextTick, onActivated, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUnitRanks } from '@/composables/useUnitRanks'
import RatioBar from '@/components/RatioBar.vue'
import InfoChip from '@/components/InfoChip.vue'
import ExpandListCell from '@/components/ExpandListCell.vue'

defineOptions({ name: 'UnitRankView' })

const filters = inject('filters')
const router = useRouter()
const { data, load, loading, formatSummary, cacheValid, dataMatchesScope } = useUnitRanks()
const pageLoading = computed(() => loading.value)

const scopedData = computed(() => (
  dataMatchesScope(data.value, filters.province, filters.city) ? data.value : null
))
const entityTab = ref('sampled')

const redTableRef = ref(null)
const greenTableRef = ref(null)

watch(entityTab, () => {
  nextTick(() => {
    if (redTableRef.value) {
      redTableRef.value.setScrollTop(0)
    }
    if (greenTableRef.value) {
      greenTableRef.value.setScrollTop(0)
    }
  })
})

function openFailureDetail(row) {
  if (!row?.company || !(row.unqualified_count > 0)) return
  router.push({
    name: 'unit-failures',
    query: {
      company: row.company,
      entity: entityTab.value,
    },
  })
}

function scrollToSection(selector) {
  const el = document.querySelector(selector)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function openRepeatCompanyDetail(row) {
  if (!row?.company || !(row.count > 0)) return
  router.push({
    name: 'unit-failures',
    query: {
      company: row.company,
      entity: 'sampled',
    },
  })
}

const redList = computed(() => (
  entityTab.value === 'sampled'
    ? (scopedData.value?.top_failure_companies || [])
    : (scopedData.value?.top_failure_manufacturers || [])
))

const greenList = computed(() => (
  entityTab.value === 'sampled'
    ? (scopedData.value?.perfect_companies || [])
    : (scopedData.value?.perfect_manufacturers || [])
))

const greenCount = computed(() => (
  entityTab.value === 'sampled'
    ? (scopedData.value?.perfect_company_count || 0)
    : (scopedData.value?.perfect_manufacturer_count || 0)
))

const entityLabel = computed(() => (
  entityTab.value === 'sampled' ? '被抽检单位' : '食品生产单位'
))

async function refresh(force = false) {
  if (!force && cacheValid(filters.province, filters.city, filters.dateRange)) return
  await load(filters.province, filters.city, filters.dateRange, force)
}

watch(() => filters.province, (next, prev) => {
  if (next !== prev) data.value = null
})
watch(() => [filters.province, filters.city, filters.dateRange], () => refresh())
onActivated(() => refresh(false))
onMounted(() => refresh(false))
defineExpose({ refresh: () => refresh(true) })
</script>

<template>
  <div v-loading="pageLoading" element-loading-text="数据较多、请耐心等候…" class="page-view page-stack rank-page">
    <InfoChip :text="formatSummary(filters.province, filters.city, filters.dateRange)" />

    <div class="tabs-nav-wrapper">
      <el-tabs v-model="entityTab" class="entity-tabs">
        <el-tab-pane label="被抽检单位" name="sampled" />
        <el-tab-pane label="食品生产单位" name="manufacturer" />
      </el-tabs>
      <div class="quick-nav-links">
        <span class="quick-nav-label">快速跳转：</span>
        <el-link type="primary" :underline="false" class="nav-link-btn" @click="scrollToSection('.panel-grid')">红绿榜</el-link>
        <el-divider direction="vertical" />
        <el-link v-if="entityTab === 'sampled'" type="primary" :underline="false" class="nav-link-btn" @click="scrollToSection('.rank-panel-col--repeat')">多次违规</el-link>
        <el-divider v-if="entityTab === 'sampled'" direction="vertical" />
        <el-link v-if="entityTab === 'sampled'" type="primary" :underline="false" class="nav-link-btn" @click="scrollToSection('.rank-panel-col--cities')">城市不合格率</el-link>
      </div>
    </div>

    <p class="page-hint rank-section-hint">
      {{ entityLabel }}与生产单位分开统计；<strong>仅统计被抽检/生产单位</strong>，检验检测机构已排除；生产单位无数据则留空。
    </p>

    <el-row :gutter="20" class="panel-grid">
      <el-col :xs="24" :xl="12">
        <el-card class="rank-card">
          <template #header>
            <div class="panel-card-header">
              <span>{{ entityLabel }}红榜（不合格率）</span>
              <span class="panel-card-count">共 {{ redList.length }} 条</span>
            </div>
          </template>
          <p class="page-hint rank-section-hint">不合格率 = 不合格数 ÷ 抽检总数；抽检次数 > 5 次才显示</p>
          <el-table
            ref="redTableRef"
            :data="redList"
            size="small"
            stripe
            max-height="480"
            class="data-table-wrap rank-table rank-table--full rank-table--paired-green"
          >
            <el-table-column label="排名" width="64" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="company" label="单位名称" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <el-link
                  v-if="row.unqualified_count > 0"
                  type="primary"
                  :underline="false"
                  @click="openFailureDetail(row)"
                >
                  {{ row.company }}
                </el-link>
                <span v-else>{{ row.company }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="total_count" label="抽检总数" width="96" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center" />
            <el-table-column label="不合格数" width="88" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center">
              <template #default="{ row }">
                <el-link
                  v-if="row.unqualified_count > 0"
                  type="primary"
                  :underline="false"
                  class="failure-count-link"
                  @click="openFailureDetail(row)"
                >
                  {{ row.unqualified_count }}
                </el-link>
                <span v-else>{{ row.unqualified_count || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column label="不合格率" min-width="160" align="right" header-align="right" class-name="col-rate" label-class-name="col-rate">
              <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :xl="12">
        <el-card class="rank-card rank-card--green">
          <template #header>
            <div class="panel-card-header">
              <span>{{ entityLabel }}绿榜（全合格）</span>
              <span class="panel-card-count">共 {{ greenCount }} 条</span>
            </div>
          </template>
          <p class="page-hint rank-section-hint">抽检次数 > 5 次且零不合格；按抽检总数排名，展示前 100 家</p>
          <el-table
            ref="greenTableRef"
            :data="greenList"
            size="small"
            stripe
            max-height="480"
            class="data-table-wrap rank-table rank-table--full rank-table--paired-green"
          >
            <el-table-column label="排名" width="64" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="company" label="单位名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="total_count" label="抽检总数" width="96" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center">
              <template #default="{ row }"><el-tag type="success" size="small">{{ row.total_count }}</el-tag></template>
            </el-table-column>
            <el-table-column label="合格率" width="88" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center">
              <template #default><el-tag type="success" size="small">100%</el-tag></template>
            </el-table-column>
            <el-table-column label="企业所在省市" min-width="140" align="center" header-align="center">
              <template #default="{ row }">
                <span>{{ row.address || (row.province ? (row.city ? row.province + ' / ' + row.city : row.province) : (row.city || '-')) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-row v-if="entityTab === 'sampled'" :gutter="20" class="panel-grid rank-panel-row">
      <el-col :xs="24" :xl="12" class="rank-panel-col rank-panel-col--repeat">
        <el-card class="rank-card">
          <template #header>
            <div class="panel-card-header">
              <span>多次违规被抽检单位</span>
              <span class="panel-card-count">共 {{ scopedData?.repeat_company_count || 0 }} 家</span>
            </div>
          </template>
          <p class="page-hint rank-section-hint">同一被抽检单位不合格次数 > 5 次；显示前 100 家</p>
          <el-table
            :data="scopedData?.repeat_companies || []"
            size="small"
            stripe
            max-height="420"
            class="data-table-wrap rank-table rank-table--full"
          >
            <el-table-column label="排名" width="64" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="company" label="被抽检单位" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <el-link
                  v-if="row.count > 0"
                  type="primary"
                  :underline="false"
                  @click="openRepeatCompanyDetail(row)"
                >
                  {{ row.company }}
                </el-link>
                <span v-else>{{ row.company }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="count" label="违规次数" width="96" class-name="col-num" label-class-name="col-num">
              <template #default="{ row }">
                <el-link
                  v-if="row.count > 0"
                  type="primary"
                  :underline="false"
                  class="failure-count-link"
                  @click="openRepeatCompanyDetail(row)"
                >
                  {{ row.count }}
                </el-link>
                <span v-else>{{ row.count || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column label="企业所在省市" min-width="140" align="center" header-align="center">
              <template #default="{ row }">
                <span>{{ row.address || (row.province ? (row.city ? row.province + ' / ' + row.city : row.province) : (row.city || '-')) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :xl="12" class="rank-panel-col rank-panel-col--cities">
        <el-card class="rank-card">
          <template #header>
            <div class="panel-card-header">
              <span>城市不合格率</span>
              <span class="panel-card-count">共 {{ (scopedData?.cities || []).length }} 条</span>
            </div>
          </template>
          <p class="page-hint rank-section-hint">按文件夹省市统计；抽检 ≥ 10 批次才显示</p>
          <el-table
            :data="scopedData?.cities || []"
            size="small"
            stripe
            max-height="420"
            class="data-table-wrap rank-table rank-table--full rank-table--paired-green"
          >
            <el-table-column label="排名" width="64" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="name" label="城市" min-width="160" show-overflow-tooltip />
            <el-table-column prop="total_count" label="抽检总数" width="96" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center" />
            <el-table-column label="不合格数" width="88" align="center" header-align="center" class-name="col-num col-num--center" label-class-name="col-num col-num--center">
              <template #default="{ row }">{{ row.unqualified_count || row.count || 0 }}</template>
            </el-table-column>
            <el-table-column label="不合格率" min-width="160" align="right" header-align="right" class-name="col-rate" label-class-name="col-rate">
              <template #default="{ row }"><RatioBar :ratio="row.ratio" /></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.entity-tabs {
  margin-bottom: 4px;
}

.rank-table--full :deep(table) {
  table-layout: fixed;
  width: 100%;
}

/* 红榜 / 绿榜 / 城市不合格率：五列对齐（排名 | 名称 | 抽检总数 | 不合格数/合格率 | 不合格率/涉及产品） */
.rank-table--paired-green :deep(.col-rank) {
  width: 64px;
}

.rank-table--paired-green :deep(.col-num.col-num--center .cell) {
  justify-content: center;
}

.rank-table :deep(.col-rate .cell) {
  display: flex;
  justify-content: flex-end;
  white-space: nowrap;
}

.rank-table :deep(.col-products .cell) {
  display: flex;
  justify-content: flex-end;
  align-items: flex-start;
  text-align: right;
  padding-inline-end: var(--table-cell-px);
}

.rank-table :deep(.col-products .cell > *),
.rank-table :deep(.col-products .cell .el-tooltip__trigger) {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  margin-left: auto;
  text-align: right;
}

.rank-panel-row {
  display: flex;
  flex-wrap: wrap;
}

/* 宽屏：左多次违规、右城市（与上方绿榜同列）；窄屏：城市紧跟绿榜 */
.rank-panel-col--cities {
  order: 1;
}

.rank-panel-col--repeat {
  order: 2;
}

@media (min-width: 1200px) {
  .rank-panel-col--repeat {
    order: 1;
  }

  .rank-panel-col--cities {
    order: 2;
  }
}

.failure-count-link {
  font-weight: 600;
}

.tabs-nav-wrapper {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 12px;
  width: 100%;
}

.tabs-nav-wrapper :deep(.el-tabs__header) {
  margin-bottom: 0 !important;
  border-bottom: none !important;
}

.quick-nav-links {
  display: flex;
  align-items: center;
  font-size: 13px;
  padding-bottom: 4px;
}

.quick-nav-label {
  color: var(--app-text-secondary);
  margin-right: 6px;
  font-weight: 500;
}

.nav-link-btn {
  font-weight: 500;
  font-size: 13px;
  transition: all 0.2s ease;
}

.nav-link-btn:hover {
  opacity: 0.8;
}
</style>
