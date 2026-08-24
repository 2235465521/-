<script setup>
import { inject, onActivated, onMounted, ref, watch } from 'vue'
import { useAnalytics } from '@/composables/useAnalytics'
import InfoChip from '@/components/InfoChip.vue'
import ExpandListCell from '@/components/ExpandListCell.vue'

const filters = inject('filters')
const { loading, data, load, formatGreenSummary } = useAnalytics()
const entityTab = ref('sampled')

const tableData = () => (
  entityTab.value === 'sampled'
    ? (data.value?.perfect_companies || [])
    : (data.value?.perfect_manufacturers || [])
)

const tableCount = () => (
  entityTab.value === 'sampled'
    ? (data.value?.perfect_company_count || 0)
    : (data.value?.perfect_manufacturer_count || 0)
)

async function refresh(force = false) {
  await load(filters.province, filters.city, filters.dateRange, force)
}

watch(() => [filters.province, filters.city, filters.dateRange], () => refresh())
onMounted(() => refresh())
onActivated(() => {
  if (data.value) return
  refresh()
})
defineExpose({ refresh: () => refresh(true) })
</script>

<template>
  <div v-loading="loading" class="page-view page-stack rank-page">
    <InfoChip :text="formatGreenSummary(filters.province, filters.city, filters.dateRange)" type="success" />

    <el-tabs v-model="entityTab" class="entity-tabs">
      <el-tab-pane label="被抽检单位" name="sampled" />
      <el-tab-pane label="食品生产单位" name="manufacturer" />
    </el-tabs>

    <p class="page-hint greenlist-hint">
      {{ entityTab === 'sampled' ? '被抽检单位' : '食品生产单位' }}抽检次数 > 5 次且零不合格；按抽检总数排名，展示前 100 家
      <template v-if="entityTab === 'manufacturer'">；生产单位地址无则留空</template>
    </p>

    <el-card class="rank-card">
      <template #header>
        <div class="panel-card-header">
          <span>{{ entityTab === 'sampled' ? '被抽检单位绿榜' : '食品生产单位绿榜' }}</span>
          <span class="panel-card-count">共 {{ tableCount() }} 条</span>
        </div>
      </template>

      <el-table
        :data="tableData()"
        size="small"
        stripe
        class="data-table-wrap rank-table"
      >
        <el-table-column label="排名" width="64" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
        <el-table-column prop="company" label="单位名称" min-width="200" show-overflow-tooltip />
        <el-table-column
          v-if="entityTab === 'manufacturer'"
          prop="address"
          label="生产单位地址"
          min-width="180"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ row.address || '-' }}</template>
        </el-table-column>
        <el-table-column prop="total_count" label="抽检总数" width="100" class-name="col-num" label-class-name="col-num">
          <template #default="{ row }"><el-tag type="success" size="small">{{ row.total_count }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="qualified_count" label="合格数" width="96" class-name="col-num" label-class-name="col-num" />
        <el-table-column label="合格率" width="88" align="center">
          <template #default><el-tag type="success" size="small">100%</el-tag></template>
        </el-table-column>
        <el-table-column label="涉及城市" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ (row.cities || []).slice(0, 4).join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="涉及产品" min-width="220" align="right" header-align="right" class-name="col-products" label-class-name="col-products">
          <template #default="{ row }">
            <ExpandListCell align="right" :values="row.products || []" :preview-max="2" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.entity-tabs {
  margin-bottom: 4px;
}
</style>
