<script setup>
import { computed } from 'vue'
import { buildPieSlices } from '@/utils/pieChart'

const props = defineProps({
  total: { type: Number, default: 0 },
  violation: { type: Number, default: 0 },
  size: { type: Number, default: 108 },
})

const chartItems = computed(() => {
  const violation = Math.max(props.violation || 0, 0)
  const total = Math.max(props.total || 0, 0)
  if (total <= violation) return []
  const qualified = total - violation
  const rows = []
  if (violation > 0) rows.push({ name: '违规次数', count: violation })
  if (qualified > 0) rows.push({ name: '合格次数', count: qualified })
  return rows
})

const slices = computed(() =>
  buildPieSlices(chartItems.value, { maxSlices: 4, mergeOther: false }),
)

const grandTotal = computed(() =>
  chartItems.value.reduce((sum, item) => sum + (item.count || 0), 0),
)

const uid = `tv-${Math.random().toString(36).slice(2, 9)}`
</script>

<template>
  <el-popover
    v-if="grandTotal > 0"
    placement="top"
    :width="248"
    trigger="hover"
    popper-class="total-violation-popover"
  >
    <template #reference>
      <slot />
    </template>
    <div class="total-violation-popover__body">
      <div
        class="total-violation-popover__chart"
        :style="{ width: `${size}px`, height: `${size}px` }"
      >
        <svg class="total-violation-popover__svg" viewBox="0 0 200 200" role="img">
          <defs>
            <linearGradient
              v-for="(slice, index) in slices"
              :id="`${uid}-grad-${index}`"
              :key="`${uid}-grad-${index}`"
              gradientUnits="userSpaceOnUse"
              :x1="100"
              :y1="24"
              :x2="100"
              :y2="176"
            >
              <stop offset="0%" :stop-color="slice.gradient[0]" stop-opacity="0.96" />
              <stop offset="45%" :stop-color="slice.gradient[1]" stop-opacity="0.82" />
              <stop offset="100%" :stop-color="slice.gradient[2]" stop-opacity="0.58" />
            </linearGradient>
          </defs>
          <path
            v-for="(slice, index) in slices"
            :key="slice.name"
            :d="slice.path"
            :fill="`url(#${uid}-grad-${index})`"
            stroke="rgba(255,255,255,0.45)"
            stroke-width="0.6"
          />
        </svg>
      </div>
      <ul class="total-violation-popover__legend">
        <li v-for="slice in slices" :key="slice.name">
          <span
            class="total-violation-popover__dot"
            :style="{
              background: `linear-gradient(135deg, ${slice.gradient[0]}, ${slice.gradient[1]})`,
            }"
          />
          <span class="total-violation-popover__label">{{ slice.name }}</span>
          <span class="total-violation-popover__value">{{ slice.count }}</span>
        </li>
        <li class="total-violation-popover__sum">
          <span>抽检总数</span>
          <span>{{ grandTotal }}</span>
        </li>
      </ul>
    </div>
  </el-popover>
  <slot v-else />
</template>

<style scoped>
.total-violation-popover__body {
  display: flex;
  align-items: center;
  gap: 12px;
}

.total-violation-popover__chart {
  flex-shrink: 0;
}

.total-violation-popover__svg {
  width: 100%;
  height: 100%;
  display: block;
}

.total-violation-popover__legend {
  margin: 0;
  padding: 0;
  list-style: none;
  flex: 1;
  min-width: 0;
}

.total-violation-popover__legend li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 1.6;
}

.total-violation-popover__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}

.total-violation-popover__label {
  flex: 1;
  color: #475569;
}

.total-violation-popover__value {
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  white-space: nowrap;
}

.total-violation-popover__sum span:last-child {
  white-space: nowrap;
}

.total-violation-popover__sum {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed #e2e8f0;
  font-weight: 600;
  color: #334155;
}
</style>
