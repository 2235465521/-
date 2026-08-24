<script setup>
import { computed } from 'vue'
import { CircleCloseFilled, InfoFilled, SuccessFilled, WarningFilled } from '@element-plus/icons-vue'

const props = defineProps({
  text: { type: String, required: true },
  type: { type: String, default: 'info' },
  icon: { type: Boolean, default: true },
})

const segments = computed(() =>
  props.text
    .split(/[·|]/)
    .map((s) => s.trim())
    .filter(Boolean),
)
</script>

<template>
  <div class="info-chip" :class="`info-chip--${type}`">
    <el-icon v-if="icon" class="info-chip__icon">
      <InfoFilled v-if="type === 'info'" />
      <SuccessFilled v-else-if="type === 'success'" />
      <WarningFilled v-else-if="type === 'warning'" />
      <CircleCloseFilled v-else-if="type === 'error'" />
    </el-icon>
    <div class="info-chip__body">
      <template v-if="segments.length > 1">
        <span v-for="(seg, index) in segments" :key="index" class="info-chip__seg">
          {{ seg }}
        </span>
      </template>
      <span v-else class="info-chip__text">{{ text }}</span>
    </div>
  </div>
</template>

<style scoped>
.info-chip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  border-radius: var(--app-radius);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.45;
  max-width: 100%;
  box-shadow: var(--app-shadow-sm);
}

.info-chip__icon {
  flex-shrink: 0;
  font-size: 18px;
  margin-top: 1px;
}

.info-chip__body {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 10px;
  min-width: 0;
}

.info-chip__seg {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.65);
  white-space: nowrap;
}

.info-chip__text {
  min-width: 0;
  line-height: 1.5;
}

.info-chip--info {
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.95), rgba(219, 234, 254, 0.75));
  border: 1px solid rgba(191, 219, 254, 0.55);
  color: #1e3a8a;
}

.info-chip--info .info-chip__seg {
  color: #1d4ed8;
}

.info-chip--success {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.95), rgba(209, 250, 229, 0.75));
  border: 1px solid rgba(167, 243, 208, 0.55);
  color: #047857;
}

.info-chip--success .info-chip__seg {
  color: #059669;
}

.info-chip--warning {
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.95), rgba(254, 243, 199, 0.75));
  border: 1px solid rgba(253, 230, 138, 0.55);
  color: #b45309;
}

.info-chip--error {
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.95), rgba(254, 226, 226, 0.75));
  border: 1px solid rgba(254, 202, 202, 0.55);
  color: #b91c1c;
}
</style>
