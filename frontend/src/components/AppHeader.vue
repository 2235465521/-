<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps({
  statusText: String,
  isScanning: Boolean,
  scanPercent: { type: Number, default: 0 },
  running: Boolean,
  backendOffline: Boolean,
})

const route = useRoute()

const statusLabel = computed(() => {
  if (props.backendOffline) return '未连接'
  if (props.running) return '扫描中'
  if (props.isScanning) return '同步中'
  return '就绪'
})

const statusClass = computed(() => {
  if (props.backendOffline) return 'is-offline'
  if (props.running) return 'is-running'
  if (props.isScanning) return 'is-sync'
  return 'is-ready'
})
</script>

<template>
  <header class="layout-header glass-header">
    <div class="header-left">
      <h1 class="header-title">{{ route.meta.title }}</h1>
      <p class="header-subtitle">{{ route.meta.desc }}</p>
    </div>

    <div class="header-right">
      <div class="status-chip" :class="statusClass">
        <span class="status-chip__dot" />
        <span class="status-chip__label">{{ statusLabel }}</span>
      </div>
      <div v-if="running" class="scan-progress">
        <el-progress :percentage="scanPercent" :stroke-width="5" :show-text="false" style="width: 100px" />
        <span class="scan-progress__text">{{ scanPercent }}%</span>
      </div>
      <div v-else class="status-hint" :title="statusText">
        {{ statusText }}
      </div>
    </div>
  </header>
</template>

<style scoped>
.header-left {
  min-width: 0;
  flex: 1;
}

.header-title {
  margin: 0;
  font-family: var(--app-font-headline);
  font-size: 17px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.header-subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--app-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(480px, 50vw);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 50%;
  overflow: hidden;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid transparent;
}

.status-chip__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-chip.is-offline {
  background: rgba(254, 242, 242, 0.9);
  border-color: rgba(254, 202, 202, 0.6);
  color: #b91c1c;
}

.status-chip.is-offline .status-chip__dot {
  background: #ef4444;
}

.status-chip.is-ready {
  background: rgba(236, 253, 245, 0.8);
  border-color: rgba(167, 243, 208, 0.5);
  color: #047857;
}

.status-chip.is-ready .status-chip__dot {
  background: #10b981;
}

.status-chip.is-sync {
  background: rgba(255, 251, 235, 0.85);
  border-color: rgba(253, 230, 138, 0.5);
  color: #b45309;
}

.status-chip.is-sync .status-chip__dot {
  background: #f59e0b;
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.status-chip.is-running {
  background: rgba(239, 246, 255, 0.85);
  border-color: rgba(191, 219, 254, 0.5);
  color: #1d4ed8;
}

.status-chip.is-running .status-chip__dot {
  background: #3b82f6;
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

.scan-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scan-progress__text {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.status-hint {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 280px;
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
