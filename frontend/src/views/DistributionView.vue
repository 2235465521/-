<script setup>
import { onActivated, inject, onMounted, watch } from 'vue'
import { useAnalytics } from '@/composables/useAnalytics'
import RatioBar from '@/components/RatioBar.vue'
import InfoChip from '@/components/InfoChip.vue'

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
    <el-row :gutter="20" class="panel-grid">
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <div class="panel-card-header"><span>不合格种类占比</span></div>
          </template>
          <p class="page-hint">仅统计「不合格项目名称」；分类不算不合格原因</p>
          <el-table :data="data?.item_types || []" size="small" stripe max-height="480" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="name" label="不合格项目" min-width="140" show-overflow-tooltip />
            <el-table-column prop="count" label="次数" width="80" class-name="col-num" label-class-name="col-num" />
            <el-table-column label="占比" width="140">
              <template #default="{ row }"><RatioBar :ratio="row.ratio" /></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <div class="panel-card-header"><span>城市不合格率</span></div>
          </template>
          <p class="page-hint">按文件夹省市统计；抽检 ≥10 批次才显示</p>
          <el-table :data="data?.cities || []" size="small" stripe max-height="480" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="name" label="城市" min-width="100" />
            <el-table-column prop="total_count" label="抽检总数" width="90" class-name="col-num" label-class-name="col-num" />
            <el-table-column label="不合格数" width="90" class-name="col-num" label-class-name="col-num">
              <template #default="{ row }">{{ row.unqualified_count || row.count || 0 }}</template>
            </el-table-column>
            <el-table-column label="不合格率" width="140">
              <template #default="{ row }"><RatioBar :ratio="row.ratio" /></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
