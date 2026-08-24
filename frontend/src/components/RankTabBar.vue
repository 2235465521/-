<script setup>
defineProps({
  options: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
})

defineEmits(['update:modelValue'])
</script>

<template>
  <el-radio-group
    :model-value="modelValue"
    class="rank-tabs"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-radio-button
      v-for="opt in options"
      :key="opt.value"
      :value="opt.value"
    >
      {{ opt.label }}
      <span class="rank-tabs__count">{{ opt.count ?? 0 }}</span>
    </el-radio-button>
  </el-radio-group>
</template>

<style scoped>
.rank-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.rank-tabs :deep(.el-radio-button__inner) {
  border: 1px solid rgba(226, 232, 240, 0.9) !important;
  border-radius: var(--app-radius-sm) !important;
  padding: 8px 14px !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  background: rgba(255, 255, 255, 0.7) !important;
  box-shadow: var(--app-shadow-sm);
  transition: all 0.2s ease !important;
}

.rank-tabs :deep(.el-radio-button:first-child .el-radio-button__inner),
.rank-tabs :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: var(--app-radius-sm) !important;
}

.rank-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: linear-gradient(135deg, var(--app-primary), var(--app-primary-bright)) !important;
  border-color: transparent !important;
  color: #fff !important;
  box-shadow: 0 6px 20px rgba(91, 156, 245, 0.32) !important;
}

.rank-tabs__count {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(15, 23, 42, 0.08);
  font-variant-numeric: tabular-nums;
}

.rank-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) .rank-tabs__count {
  background: rgba(255, 255, 255, 0.22);
}
</style>
