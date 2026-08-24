<script setup>
import { computed } from 'vue'

const props = defineProps({ ratio: { type: Number, default: 0 } })

const clamped = computed(() => Math.min(Math.max(props.ratio, 0), 100))

const tier = computed(() => {
  if (clamped.value >= 50) return 'high'
  if (clamped.value >= 20) return 'mid'
  return 'low'
})
</script>

<template>
  <div class="ratio-bar">
    <span class="ratio-value" :class="`ratio-value--${tier}`">{{ clamped }}%</span>
    <div class="ratio-track">
      <div
        class="ratio-fill"
        :class="`ratio-fill--${tier}`"
        :style="{ width: `${clamped}%` }"
      />
    </div>
  </div>
</template>

<style scoped>
.ratio-bar {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  white-space: nowrap;
}

.ratio-value {
  min-width: 3.6em;
  font-size: 12px;
  font-weight: 700;
  text-align: right;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.ratio-value--low { color: #ca8a04; }
.ratio-value--mid { color: #f59e0b; }
.ratio-value--high { color: var(--app-ratio-fail-text); }

.ratio-track {
  width: 56px;
  flex-shrink: 0;
  height: 8px;
  background: var(--app-ratio-track);
  border-radius: 999px;
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}

.ratio-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.55s cubic-bezier(0.22, 1, 0.36, 1);
  min-width: 2px;
}

.ratio-fill--low {
  background: linear-gradient(90deg, #fef08a, #fde047);
  box-shadow: 0 0 10px rgba(253, 224, 71, 0.35);
}

.ratio-fill--mid {
  background: linear-gradient(90deg, var(--app-ratio-fail), var(--app-ratio-fail-end));
  box-shadow: 0 0 10px rgba(253, 164, 175, 0.35);
}

.ratio-fill--high {
  background: linear-gradient(90deg, var(--app-ratio-fail-end), #f43f5e);
  box-shadow: 0 0 12px rgba(251, 113, 133, 0.4);
}
</style>
