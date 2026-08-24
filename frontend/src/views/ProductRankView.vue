<script setup>
import { computed, inject, onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProductRanks } from '@/composables/useProductRanks'
import RatioBar from '@/components/RatioBar.vue'
import InfoChip from '@/components/InfoChip.vue'
import RankTabBar from '@/components/RankTabBar.vue'
import ItemTypePieChart from '@/components/ItemTypePieChart.vue'
import MiniItemPieChart from '@/components/MiniItemPieChart.vue'
import { resolveBreakdownItems } from '@/utils/format'
import { InfoFilled } from '@element-plus/icons-vue'

defineOptions({ name: 'ProductRankView' })

const route = useRoute()
const router = useRouter()
const filters = inject('filters')
const { data, loadError, needsBackendRefresh, load, loading, formatSummary, cacheValid, dataMatchesScope } = useProductRanks()
const pageLoading = computed(() => loading.value)

const scopedData = computed(() => (
  dataMatchesScope(data.value, filters.province, filters.city) ? data.value : null
))

async function refresh(force = false) {
  if (!force && cacheValid(filters.province, filters.city, filters.dateRange)) return
  await load(filters.province, filters.city, filters.dateRange, force)
}

function openProductFailureDetail(row) {
  if (!row?.product || !(row.unqualified_count > 0)) return
  router.push({
    name: 'product-failures',
    query: {
      product: row.product,
    },
  })
}

const ITEM_TYPES_PIE_SLICES = 30

const itemTypesGrandTotal = computed(() => {
  const total = scopedData.value?.item_types_total
  if (total > 0) return total
  return (scopedData.value?.item_types || []).reduce((sum, item) => sum + (item.count || 0), 0)
})

const TAB_VALUES = new Set(['failure_rate', 'item_types', 'repeat'])
const rankType = ref('item_types')

const rankOptions = computed(() => {
  const d = scopedData.value || {}
  return [
    {
      value: 'failure_rate',
      label: '产品不合格率',
      hint: '不合格率 = 不合格数 ÷ 抽检总数；抽检总数 ≥ 20 批次才显示；仅展示前 50 名',
      count: (d.top_failure_products || []).length,
    },
    {
      value: 'item_types',
      label: '不合格项目占比',
      hint: '按不合格项目名称统计项次，同一批次多项分别计数',
      count: d.item_types_unique || (d.item_types || []).length,
    },
    {
      value: 'repeat',
      label: '高频违规产品',
      hint: '同一产品多次出现不合格记录；仅展示前 50 名',
      count: (d.repeat_product_count || 0),
    },
  ]
})

const emptyText = computed(() => {
  if (rankType.value === 'failure_rate') {
    return '暂无产品不合格率数据'
  }
  if (rankType.value === 'repeat') {
    return '暂无高频违规产品数据'
  }
  return '暂无数据'
})

const activeOption = computed(
  () => rankOptions.value.find((o) => o.value === rankType.value) || rankOptions.value[0],
)

let filterTimer = null
watch(
  () => [filters.province, filters.city, filters.dateRange],
  (newVal, oldVal) => {
    if (!oldVal || newVal[0] !== oldVal[0] || newVal[1] !== oldVal[1] || JSON.stringify(newVal[2]) !== JSON.stringify(oldVal[2])) {
      data.value = null
    }
    clearTimeout(filterTimer)
    filterTimer = setTimeout(() => refresh(false), 300)
  },
  { deep: true },
)
onActivated(() => {
  refresh(false)
})
onMounted(() => {
  const tab = route.query.tab
  if (typeof tab === 'string' && TAB_VALUES.has(tab)) rankType.value = tab
  refresh(false)
})
defineExpose({ refresh: () => refresh(true) })
</script>

<template>
  <div v-loading="pageLoading" element-loading-text="数据较多、请耐心等候…" class="page-view page-stack rank-page">
    <InfoChip :text="formatSummary(filters.province, filters.city, filters.dateRange)" />
    <el-alert
      v-if="loadError && !loading"
      type="error"
      :closable="false"
      show-icon
      :title="loadError"
      class="rank-stale-alert"
    >
      <el-button type="primary" link @click="refresh(true)">立即重试</el-button>
    </el-alert>
    <el-alert
      v-if="needsBackendRefresh && rankType === 'item_types'"
      type="warning"
      :closable="false"
      show-icon
      title="统计口径已更新，请重启后端并刷新页面以查看最新数据"
      class="rank-stale-alert"
    />

    <div class="rank-toolbar">
      <RankTabBar v-model="rankType" :options="rankOptions" />
      <p v-if="activeOption?.hint" class="page-hint rank-hint">
        <el-icon class="rank-hint-icon"><InfoFilled /></el-icon>
        <span>{{ activeOption.hint }}</span>
      </p>
    </div>

    <el-card class="rank-card">
      <template #header>
        <div class="panel-card-header">
          <span>{{ activeOption?.label }}</span>
          <span class="panel-card-count">
            {{ rankType === 'item_types' ? `共 ${activeOption?.count || 0} 类` : `共 ${activeOption?.count || 0} 条` }}
          </span>
        </div>
      </template>

      <el-table
        v-if="rankType === 'failure_rate'"
        :data="scopedData?.top_failure_products || []"
        size="small"
        stripe
        class="data-table-wrap rank-table rank-table--fixed"
        style="width: 100%"
      >
        <el-table-column label="排名" width="56" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
        <el-table-column prop="product" label="小类" width="120" show-overflow-tooltip class-name="col-scope" label-class-name="col-scope">
          <template #default="{ row }">
            <el-link
              v-if="row.unqualified_count > 0"
              type="primary"
              :underline="false"
              @click="openProductFailureDetail(row)"
            >
              {{ row.product }}
            </el-link>
            <span v-else>{{ row.product }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="total_count"
          label="抽检总数"
          width="96"
          align="center"
          header-align="center"
          class-name="col-num col-num--center"
          label-class-name="col-num col-num--center"
        />
        <el-table-column
          prop="unqualified_count"
          label="不合格数"
          width="96"
          align="center"
          header-align="center"
          class-name="col-num col-num--center"
          label-class-name="col-num col-num--center"
        >
          <template #default="{ row }">
            <el-link
              v-if="row.unqualified_count > 0"
              type="primary"
              :underline="false"
              class="failure-count-link"
              @click="openProductFailureDetail(row)"
            >
              {{ row.unqualified_count }}
            </el-link>
            <span v-else>{{ row.unqualified_count || 0 }}</span>
          </template>
        </el-table-column>
        <el-table-column
          label="不合格率"
          width="130"
          align="center"
          header-align="center"
          class-name="col-rate"
          label-class-name="col-rate"
        >
          <template #default="{ row }">
            <RatioBar :ratio="row.failure_rate" />
          </template>
        </el-table-column>
        <el-table-column
          label="不合格原因占比"
          min-width="320"
          align="left"
          header-align="left"
          class-name="col-pie"
          label-class-name="col-pie"
        >
          <template #default="{ row }">
            <MiniItemPieChart :items="resolveBreakdownItems(row)" :title="row.product" show-legend />
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="emptyText" :image-size="80" />
        </template>
      </el-table>

      <ItemTypePieChart
        v-else-if="rankType === 'item_types'"
        :items="scopedData?.item_types || []"
        :grand-total="itemTypesGrandTotal"
        :max-slices="ITEM_TYPES_PIE_SLICES"
      />

      <el-table
        v-else
        :data="scopedData?.repeat_products || []"
        size="small"
        stripe
        class="data-table-wrap rank-table rank-table--fixed"
        style="width: 100%"
      >
        <el-table-column label="排名" width="56" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
        <el-table-column prop="product" label="小类" width="120" show-overflow-tooltip class-name="col-scope" label-class-name="col-scope" />
        <el-table-column
          prop="total_count"
          label="抽检总数"
          width="96"
          align="center"
          header-align="center"
          class-name="col-num col-num--center"
          label-class-name="col-num col-num--center"
        />
        <el-table-column
          prop="count"
          label="违规次数"
          width="96"
          align="center"
          header-align="center"
          class-name="col-num col-num--center"
          label-class-name="col-num col-num--center"
        >
          <template #default="{ row }">
            <el-tag type="warning" size="small">{{ row.count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="违规原因占比"
          min-width="320"
          align="left"
          header-align="left"
          class-name="col-pie"
          label-class-name="col-pie"
        >
          <template #default="{ row }">
            <MiniItemPieChart :items="resolveBreakdownItems(row)" :title="row.product" show-legend />
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="emptyText" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>
