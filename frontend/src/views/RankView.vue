<script setup>
import { onActivated, inject, onMounted, watch } from 'vue'
import { useAnalytics } from '@/composables/useAnalytics'
import RatioBar from '@/components/RatioBar.vue'
import InfoChip from '@/components/InfoChip.vue'
import { formatMainReasons } from '@/utils/format'

const filters = inject('filters')
const { loading, data, load, formatSummary } = useAnalytics()

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
  <div v-loading="loading" class="page-view page-stack">
    <InfoChip :text="formatSummary(filters.province, filters.city, filters.dateRange)" />
    <p class="page-desc">不合格率 = 不合格批次 ÷ 抽检总数；单位至少 10 批次、产品至少 20 批次才纳入</p>
    <el-row :gutter="20" class="panel-grid">
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <div class="panel-card-header">
              <span>单位不合格率 TOP</span>
            </div>
          </template>
          <el-table :data="data?.top_failure_companies || []" size="small" stripe max-height="520" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="company" label="单位名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="total_count" label="抽检总数" width="90" class-name="col-num" label-class-name="col-num" />
            <el-table-column prop="unqualified_count" label="不合格数" width="90" class-name="col-num" label-class-name="col-num" />
            <el-table-column label="不合格率" width="150">
              <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <div class="panel-card-header">
              <span>产品不合格率 TOP</span>
            </div>
          </template>
          <el-table :data="data?.top_failure_products || []" size="small" stripe max-height="520" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="product" label="产品名称" min-width="120" show-overflow-tooltip />
            <el-table-column prop="total_count" label="抽检总数" width="90" class-name="col-num" label-class-name="col-num" />
            <el-table-column prop="unqualified_count" label="不合格数" width="90" class-name="col-num" label-class-name="col-num" />
            <el-table-column label="不合格率" width="130">
              <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
            </el-table-column>
            <el-table-column label="主要不合格原因" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ formatMainReasons(row.main_reasons) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
