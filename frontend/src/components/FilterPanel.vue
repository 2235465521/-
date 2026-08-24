<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshLeft, Search, Location, Operation, InfoFilled, ArrowUp } from '@element-plus/icons-vue'
import { dateRangePickerShortcuts, disabledFutureDate } from '@/utils/dateRangePicker'

const props = defineProps({
  provinces: Array,
  cities: Array,
  province: String,
  city: String,
  dateRange: Array,
  search: Object,
  showScope: Boolean,
  showSearch: Boolean,
})

const emit = defineEmits([
  'update:province',
  'update:city',
  'update:dateRange',
  'update:search',
  'province-change',
  'city-change',
  'date-change',
  'clear-search',
  'clear-scope',
])

const route = useRoute()
const isUnqualified = computed(() => route.name === 'unqualified')

function patchSearch(key, value) {
  emit('update:search', { ...props.search, [key]: value })
}

const collapsed = ref(localStorage.getItem('filter_panel_collapsed') === 'true')
function toggleCollapse() {
  collapsed.value = !collapsed.value
  localStorage.setItem('filter_panel_collapsed', String(collapsed.value))
}

const activeFilterTags = computed(() => {
  const tags = []
  if (props.province && props.province !== '全部') {
    tags.push(props.province)
  }
  if (props.city && props.city !== '全部') {
    tags.push(props.city)
  }
  if (props.dateRange && props.dateRange.length === 2) {
    tags.push(`${props.dateRange[0]}至${props.dateRange[1]}`)
  }
  if (props.search?.company?.trim()) {
    tags.push(`单位:${props.search.company.trim()}`)
  }
  if (props.search?.product?.trim()) {
    tags.push(`原名:${props.search.product.trim()}`)
  }
  if (props.search?.item?.trim()) {
    tags.push(`不合格:${props.search.item.trim()}`)
  }
  if (props.search?.category?.trim()) {
    tags.push(`分类:${props.search.category.trim()}`)
  }
  return tags
})
</script>

<template>
  <div v-if="showScope || showSearch" class="glass-card filter-panel" :class="{ 'filter-panel--collapsed': collapsed }">
    <!-- Decorative subtle top accent gradient -->
    <div class="filter-card-top-bar" />

    <!-- Toggle Header Bar -->
    <div class="filter-panel-header" @click="toggleCollapse">
      <div class="filter-panel-header__left">
        <span class="filter-panel-header__title">条件筛选</span>
        <!-- Filter Summary Tags when collapsed -->
        <div v-if="collapsed" class="filter-summary-tags">
          <el-tag v-for="tag in activeFilterTags" :key="tag" size="small" type="info" round class="filter-summary-tag">
            {{ tag }}
          </el-tag>
          <span v-if="!activeFilterTags.length" class="filter-summary-placeholder">显示全库数据</span>
        </div>
      </div>
      <div class="filter-panel-header__right">
        <el-button link class="btn-toggle">
          {{ collapsed ? '展开筛选' : '收起筛选' }}
          <el-icon class="btn-toggle__icon" :class="{ 'is-collapsed': collapsed }">
            <ArrowUp />
          </el-icon>
        </el-button>
      </div>
    </div>

    <!-- Collapsible Body -->
    <div v-show="!collapsed" class="filter-panel-body">
      <div v-if="showScope" class="filter-section">
        <div class="filter-section-header">
          <div class="filter-section-title">
            <div class="title-badge title-badge--blue">
              <el-icon><Location /></el-icon>
            </div>
            <span>数据范围</span>
          </div>
          <div class="filter-scope-hint">
            <el-icon><InfoFilled /></el-icon>
            <span>时间筛选依据公告文件夹中的年份；留空则包含全部年份</span>
          </div>
        </div>

        <div class="filter-grid filter-grid--scope">
          <div class="filter-field">
            <label>省份</label>
            <el-select
              :model-value="province"
              class="filter-control"
              placeholder="全部省份"
              @update:model-value="emit('update:province', $event); emit('province-change')"
            >
              <el-option label="全部省份" value="全部" />
              <el-option v-for="p in provinces || []" :key="p" :label="p" :value="p" />
            </el-select>
          </div>
          <div class="filter-field">
            <label>城市</label>
            <el-select
              :model-value="city"
              class="filter-control"
              placeholder="全部城市"
              @update:model-value="emit('update:city', $event); emit('city-change')"
            >
              <el-option label="全部城市" value="全部" />
              <el-option v-for="c in cities || []" :key="c" :label="c" :value="c" />
            </el-select>
          </div>
          <div class="filter-field filter-field--date">
            <label>时间范围</label>
            <el-date-picker
              :model-value="dateRange"
              type="daterange"
              class="filter-control filter-control--date"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              value-format="YYYY-MM-DD"
              unlink-panels
              clearable
              :disabled-date="disabledFutureDate"
              :shortcuts="dateRangePickerShortcuts"
              @update:model-value="emit('update:dateRange', $event); emit('date-change')"
            />
          </div>
          <div class="filter-actions">
            <el-button plain class="btn-reset" :icon="RefreshLeft" @click="emit('clear-scope')">清除范围</el-button>
          </div>
        </div>
      </div>

      <div v-if="showScope && showSearch" class="filter-divider" />

      <div v-if="showSearch" class="filter-section">
        <div class="filter-section-header">
          <div class="filter-section-title">
            <div class="title-badge title-badge--indigo">
              <el-icon><Operation /></el-icon>
            </div>
            <span>筛选条件</span>
          </div>
        </div>

        <div class="filter-grid filter-grid--search" :class="{ 'has-item': isUnqualified }">
          <div class="filter-field">
            <label>单位名称</label>
            <el-input
              :model-value="search.company"
              placeholder="输入单位名称"
              clearable
              class="filter-control"
              :prefix-icon="Search"
              @update:model-value="patchSearch('company', $event)"
            />
          </div>
          <div class="filter-field">
            <label>原名</label>
            <el-input
              :model-value="search.product"
              placeholder="输入食品原名"
              clearable
              class="filter-control"
              @update:model-value="patchSearch('product', $event)"
            />
          </div>
          <div v-if="isUnqualified" class="filter-field">
            <label>不合格项目</label>
            <el-input
              :model-value="search.item"
              placeholder="输入不合格项目"
              clearable
              class="filter-control"
              @update:model-value="patchSearch('item', $event)"
            />
          </div>
          <div class="filter-field">
            <label>食品分类</label>
            <el-input
              :model-value="search.category"
              placeholder="输入小类/分类"
              clearable
              class="filter-control"
              @update:model-value="patchSearch('category', $event)"
            />
          </div>
          <div class="filter-actions">
            <el-button plain class="btn-reset" :icon="RefreshLeft" @click="emit('clear-search')">清除</el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-panel {
  --filter-control-h: 34px;
  position: relative;
  padding: 12px 18px 14px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  box-shadow: 0 8px 24px -4px rgba(59, 130, 246, 0.06), 0 2px 8px rgba(0, 0, 0, 0.02);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.filter-panel:hover {
  box-shadow: 0 12px 28px -4px rgba(59, 130, 246, 0.1), 0 4px 12px rgba(0, 0, 0, 0.02);
}

.filter-card-top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #3b82f6 0%, #6366f1 50%, #8b5cf6 100%);
}

.filter-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.filter-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.title-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  font-size: 12px;
}

.title-badge--blue {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  color: #2563eb;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.title-badge--indigo {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  color: #4f46e5;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.filter-scope-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  padding: 2px 8px;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  line-height: 1.3;
}

.filter-scope-hint .el-icon {
  color: #3b82f6;
  font-size: 12px;
}

.filter-divider {
  height: 1px;
  background: linear-gradient(90deg, rgba(226, 232, 240, 0.3) 0%, rgba(203, 213, 225, 0.75) 20%, rgba(203, 213, 225, 0.75) 80%, rgba(226, 232, 240, 0.3) 100%);
  margin: 10px 0;
}

.filter-grid {
  gap: 8px 12px !important;
}

.filter-field label {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 4px;
  line-height: 1.2;
}

.filter-control {
  width: 100%;
}

.filter-control :deep(.el-input__wrapper),
.filter-control :deep(.el-select__wrapper) {
  height: var(--filter-control-h) !important;
  min-height: var(--filter-control-h) !important;
  line-height: var(--filter-control-h) !important;
  border-radius: 6px !important;
  background-color: #f8fafc !important;
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
  font-size: 12.5px !important;
  padding: 0 10px !important;
  transition: all 0.2s ease !important;
}

.filter-control :deep(.el-input__wrapper:hover),
.filter-control :deep(.el-select__wrapper:hover) {
  background-color: #ffffff !important;
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}

.filter-control :deep(.el-input__wrapper.is-focus),
.filter-control :deep(.el-select__wrapper.is-focused) {
  background-color: #ffffff !important;
  box-shadow: 0 0 0 2px #3b82f6 inset, 0 0 0 3px rgba(59, 130, 246, 0.12) !important;
}

.filter-control--date {
  width: 100%;
}

.filter-field--date {
  min-width: 0;
  max-width: 100%;
}

.btn-reset {
  height: var(--filter-control-h) !important;
  border-radius: 6px !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  padding: 0 12px !important;
  background-color: #f1f5f9 !important;
  border-color: #cbd5e1 !important;
  color: #475569 !important;
  transition: all 0.2s ease !important;
}

.btn-reset:hover {
  background-color: #e2e8f0 !important;
  color: #1e293b !important;
  border-color: #94a3b8 !important;
}

.filter-panel--collapsed {
  padding: 8px 18px !important;
}

.filter-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  min-height: 24px;
}

.filter-panel-header__left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.filter-panel-header__title {
  font-size: 13.5px;
  font-weight: 700;
  color: #0f172a;
}

.filter-summary-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}

.filter-summary-tag {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filter-summary-placeholder {
  font-size: 12px;
  color: #94a3b8;
}

.btn-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px !important;
  color: #64748b !important;
}

.btn-toggle:hover {
  color: #3b82f6 !important;
}

.btn-toggle__icon {
  transition: transform 0.25s ease;
}

.btn-toggle__icon.is-collapsed {
  transform: rotate(180deg);
}

.filter-panel-body {
  margin-top: 12px;
}
</style>

