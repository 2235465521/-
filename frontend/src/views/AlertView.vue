<script setup>
import { onActivated, inject, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalytics } from '@/composables/useAnalytics'
import ExpandListCell from '@/components/ExpandListCell.vue'

const filters = inject('filters')
const router = useRouter()
const { loading, data, load, formatSummary } = useAnalytics()

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
            <div class="panel-card-header">
              <span>多次违规公司</span>
              <span class="panel-card-count">{{ data?.repeat_company_count || 0 }} 家</span>
            </div>
          </template>
          <el-table :data="data?.repeat_companies || []" size="small" stripe max-height="520" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="company" label="公司名称" min-width="140" show-overflow-tooltip>
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
            <el-table-column prop="count" label="违规次数" width="90" class-name="col-num" label-class-name="col-num">
              <template #default="{ row }">
                <el-link
                  v-if="row.count > 0"
                  type="primary"
                  :underline="false"
                  @click="openRepeatCompanyDetail(row)"
                >
                  {{ row.count }}
                </el-link>
                <span v-else>{{ row.count || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="ratio" label="占比" width="70" class-name="col-num" label-class-name="col-num">
              <template #default="{ row }">{{ row.ratio }}%</template>
            </el-table-column>
            <el-table-column label="涉及产品" min-width="160" align="right" header-align="right" class-name="col-products" label-class-name="col-products">
              <template #default="{ row }">
                <ExpandListCell align="right" :values="row.products || []" :preview-max="3" />
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <div class="panel-card-header">
              <span>高频违规产品</span>
              <span class="panel-card-count">{{ data?.repeat_product_count || 0 }} 种</span>
            </div>
          </template>
          <el-table :data="data?.repeat_products || []" size="small" stripe max-height="520" class="data-table-wrap">
            <el-table-column label="排名" width="60" type="index" :index="(i) => i + 1" class-name="col-rank" label-class-name="col-rank" />
            <el-table-column prop="product" label="产品名称" min-width="120" show-overflow-tooltip />
            <el-table-column prop="count" label="违规次数" width="90" class-name="col-num" label-class-name="col-num">
              <template #default="{ row }"><el-tag type="warning" size="small">{{ row.count }}</el-tag></template>
            </el-table-column>
            <el-table-column label="占比" width="130">
              <template #default="{ row }"><RatioBar :ratio="row.ratio" /></template>
            </el-table-column>
            <el-table-column label="主要不合格项目" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.items || []).slice(0, 3).join('、') || '-' }}</template>
            </el-table-column>
            <el-table-column label="涉及省份" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.provinces || []).slice(0, 6).join('、') || '-' }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
