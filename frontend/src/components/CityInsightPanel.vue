<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getData, openSourceFile } from '@/api'
import RatioBar from '@/components/RatioBar.vue'
import { buildDateQueryParams, displayReason } from '@/utils/format'

const DETAIL_DIALOG_WIDTH_KEY = 'region_insight_detail_dialog_width'
const DETAIL_DIALOG_MIN_WIDTH = 560
const DETAIL_DIALOG_DEFAULT_WIDTH = 920

const props = defineProps({
  loading: { type: Boolean, default: false },
  insights: { type: Object, default: null },
  scopeLabel: { type: String, default: '' },
  province: { type: String, default: '' },
  city: { type: String, default: '全部' },
  dateRange: { type: Array, default: null },
  topLimit: { type: Number, default: 3 },
})

const emit = defineEmits(['update:topLimit'])

const topOptions = [3, 5, 10, 20, 50]

const topLimitModel = computed({
  get: () => props.topLimit,
  set: (value) => emit('update:topLimit', value),
})

const detailVisible = ref(false)
const detailCompany = ref('')
const detailLoading = ref(false)
const detailItems = ref([])
const detailDialogWidth = ref(DETAIL_DIALOG_DEFAULT_WIDTH)
const resizing = ref(false)

const hasRiskCompanies = computed(() => {
  const list = props.insights?.top_risk_companies || []
  return list.some(item => (item.failure_rate || 0) > 0)
})

const hasRiskProducts = computed(() => {
  const list = props.insights?.top_risk_products || []
  return list.some(item => (item.failure_rate || 0) > 0)
})

const riskCompaniesData = computed(() => {
  const list = props.insights?.top_risk_companies || []
  return list.filter(item => (item.failure_rate || 0) > 0)
})

const riskCompaniesEmptyText = computed(() => {
  const originalList = props.insights?.top_risk_companies || []
  if (originalList.length > 0 && !hasRiskCompanies.value) {
    return '未检出风险企业'
  }
  return '样本不足'
})

const riskProductsData = computed(() => {
  const list = props.insights?.top_risk_products || []
  return list.filter(item => (item.failure_rate || 0) > 0)
})

const riskProductsEmptyText = computed(() => {
  const originalList = props.insights?.top_risk_products || []
  if (originalList.length > 0 && !hasRiskProducts.value) {
    return '未检出风险产品'
  }
  return '样本不足'
})

const companyMinSamples = computed(() => {
  const total = props.insights?.total_count || 0
  if (total <= 0) return 3
  if (total <= 15) return 1
  if (total <= 50) return 2
  if (total <= 200) return 2
  return 3
})

const productMinSamples = computed(() => {
  const total = props.insights?.total_count || 0
  if (total <= 0) return 5
  if (total <= 15) return 1
  if (total <= 50) return 2
  if (total <= 200) return 3
  return 5
})

function detailDialogMaxWidth() {
  return Math.min(1400, Math.floor(window.innerWidth * 0.96))
}

function clampDialogWidth(width) {
  return Math.min(detailDialogMaxWidth(), Math.max(DETAIL_DIALOG_MIN_WIDTH, width))
}

onMounted(() => {
  const saved = Number(localStorage.getItem(DETAIL_DIALOG_WIDTH_KEY))
  if (saved > 0) {
    detailDialogWidth.value = clampDialogWidth(saved)
  }
})

function startDialogResize(event) {
  const startX = event.clientX
  const startWidth = detailDialogWidth.value
  resizing.value = true

  function onMove(ev) {
    detailDialogWidth.value = clampDialogWidth(startWidth + (ev.clientX - startX))
  }

  function onUp() {
    resizing.value = false
    localStorage.setItem(DETAIL_DIALOG_WIDTH_KEY, String(detailDialogWidth.value))
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

async function handleOpenFile(path) {
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

async function openCompanyDetail(company) {
  if (!company) return
  detailCompany.value = company
  detailVisible.value = true
  detailLoading.value = true
  detailItems.value = []
  try {
    const params = {
      type: 'unqualified',
      province: props.province || '全部',
      city: props.city || '全部',
      company,
      page: 1,
      page_size: 200,
      ...buildDateQueryParams(props.dateRange),
    }
    const { data } = await getData(params)
    detailItems.value = data.items || []
    if (!detailItems.value.length) {
      ElMessage.info('未找到该单位的不合格记录')
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '加载不合格明细失败')
  } finally {
    detailLoading.value = false
  }
}
</script>

<template>
  <aside class="region-insight-panel">
    <div class="region-insight-panel__header">
      <div>
        <h5>{{ scopeLabel }} · 抽检洞察</h5>
        <p v-if="insights" class="region-insight-panel__meta">
          {{ city && city !== '全部' ? `${province}-${city}` : province }} · 合计 {{ (insights.total_count || 0).toLocaleString() }} 项 · 不合格率 {{ insights.failure_rate || 0 }}%
        </p>
      </div>
      <div class="region-insight-panel__actions">
        <span class="region-insight-panel__top-label">TOP</span>
        <el-select v-model="topLimitModel" size="small" class="region-insight-panel__top-select">
          <el-option v-for="n in topOptions" :key="n" :label="String(n)" :value="n" />
        </el-select>
      </div>
    </div>

    <div v-loading="loading" class="region-insight-panel__list">
      <section class="region-insight-card region-insight-card--risk">
        <h6>最危险企业 TOP{{ topLimit }}</h6>
        <el-table :data="riskCompaniesData" size="small" stripe :empty-text="riskCompaniesEmptyText" max-height="250">
          <el-table-column type="index" label="#" width="30" />
          <el-table-column prop="company" label="企业" min-width="100">
            <template #default="{ row }">
              <el-link type="primary" :underline="false" @click="openCompanyDetail(row.company)">
                {{ row.company }}
              </el-link>
            </template>
          </el-table-column>
          <el-table-column prop="total_count" label="抽检" width="50" align="right" />
          <el-table-column label="不合格率" width="120">
            <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
          </el-table-column>
        </el-table>
      </section>

      <section class="region-insight-card region-insight-card--risk">
        <h6>最危险产品 TOP{{ topLimit }}</h6>
        <el-table :data="riskProductsData" size="small" stripe :empty-text="riskProductsEmptyText" max-height="250">
          <el-table-column type="index" label="#" width="30" />
          <el-table-column prop="product" label="产品" min-width="100" />
          <el-table-column prop="total_count" label="抽检" width="50" align="right" />
          <el-table-column label="不合格率" width="120">
            <template #default="{ row }"><RatioBar :ratio="row.failure_rate" /></template>
          </el-table-column>
        </el-table>
      </section>

      <section class="region-insight-card region-insight-card--safe">
        <h6>最优秀企业 TOP{{ topLimit }}</h6>
        <el-table :data="insights?.top_safe_companies || []" size="small" stripe empty-text="样本不足" max-height="250">
          <el-table-column type="index" label="#" width="30" />
          <el-table-column prop="company" label="企业" min-width="100" />
          <el-table-column prop="total_count" label="抽检" width="50" align="right" />
          <el-table-column label="合格率" width="80" align="center">
            <template #default="{ row }">
              <el-tag type="success" size="small">{{ row.pass_rate }}%</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <p v-if="insights" class="region-insight-panel__hint">
        * 注：为确保排名的统计学效力，榜单设有最低抽检频次门槛（当前区域企业需抽检满 {{ companyMinSamples }} 次，产品需满 {{ productMinSamples }} 次）。若不合格实体未达到频次门槛，则不在此列表中显示。
      </p>
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="`${detailCompany} · 不合格抽检明细`"
      :width="`${detailDialogWidth}px`"
      :append-to-body="true"
      destroy-on-close
      class="region-insight-detail-dialog"
      :class="{ 'is-resizing': resizing }"
    >
      <button
        type="button"
        class="region-insight-detail-dialog__resize"
        title="按住拖动，左右调整弹窗宽度"
        aria-label="拖动调整弹窗宽度"
        @mousedown.prevent="startDialogResize"
      >
        <span class="region-insight-detail-dialog__resize-grip" aria-hidden="true" />
      </button>
      <p v-if="detailItems.length" class="region-insight-detail-dialog__meta">
        共 {{ detailItems.length }} 条不合格记录 · 点击源文件可打开对应抽检附件
      </p>
      <el-table
        v-loading="detailLoading"
        :data="detailItems"
        size="small"
        stripe
        max-height="420"
        class="region-insight-detail-dialog__table"
        empty-text="暂无不合格记录"
      >
        <el-table-column type="index" label="#" width="48" />
        <el-table-column prop="product" label="产品" min-width="120" show-overflow-tooltip />
        <el-table-column prop="unqualified_item" label="不合格项目" min-width="120" show-overflow-tooltip />
        <el-table-column label="原因" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ displayReason(row) }}</template>
        </el-table-column>
        <el-table-column label="抽样省市" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ row.province_city || row.province || '-' }}</template>
        </el-table-column>
        <el-table-column label="源文件" min-width="160">
          <template #default="{ row }">
            <el-link type="primary" @click="handleOpenFile(row.file_source || row.source_file)">
              {{ row.source_file_name || '打开源文件' }}{{ row.source_sheet ? ` [${row.source_sheet}]` : '' }}
            </el-link>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </aside>
</template>

<style scoped>
.region-insight-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  height: 100%;
  padding: 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid var(--app-glass-border);
  box-shadow: 0 8px 24px rgba(91, 156, 245, 0.08);
  backdrop-filter: blur(12px);
}

.region-insight-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
}

.region-insight-panel__header h5 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 700;
  color: var(--app-text);
}

.region-insight-panel__meta {
  margin: 0;
  font-size: 12px;
  color: var(--app-text-secondary);
}

.region-insight-panel__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.region-insight-panel__top-label {
  font-size: 12px;
  color: var(--app-text-secondary);
}

.region-insight-panel__top-select {
  width: 72px;
}

.region-insight-panel__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.region-insight-card {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(248, 250, 252, 0.75);
  flex-shrink: 0;
}

.region-insight-card :deep(.el-table .cell) {
  padding: 0 6px !important;
}

.region-insight-card h6 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}

.region-insight-card--risk h6 {
  color: var(--app-ratio-fail-text);
}

.region-insight-card--safe h6 {
  color: var(--app-ratio-pass-text);
}

.region-insight-detail-dialog__meta {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--app-text-secondary);
}

:deep(.region-insight-detail-dialog.el-dialog) {
  position: relative;
  max-width: 96vw;
  overflow: visible;
}

:deep(.region-insight-detail-dialog .el-dialog__body) {
  position: relative;
  overflow: visible;
}

:deep(.region-insight-detail-dialog.is-resizing.el-dialog) {
  transition: none;
}

.region-insight-detail-dialog__resize {
  position: absolute;
  top: 50%;
  right: -10px;
  z-index: 2;
  transform: translateY(-50%);
  width: 14px;
  height: 56px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.55);
  border-radius: 8px;
  background: linear-gradient(180deg, #fff 0%, #f1f5f9 100%);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
  cursor: ew-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.region-insight-detail-dialog__resize:hover {
  border-color: var(--app-primary);
  box-shadow: 0 2px 12px rgba(91, 156, 245, 0.28);
}

.region-insight-detail-dialog__resize-grip {
  width: 4px;
  height: 22px;
  border-radius: 2px;
  background: repeating-linear-gradient(
    to bottom,
    #94a3b8 0,
    #94a3b8 2px,
    transparent 2px,
    transparent 5px
  );
}

.region-insight-detail-dialog__table {
  width: 100%;
}

.region-insight-panel__hint {
  margin: 12px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--app-text-muted);
  border-top: 1px dashed var(--app-border-light);
  padding-top: 8px;
}
</style>
