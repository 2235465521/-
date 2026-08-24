<script setup>
import { computed, ref, watch } from 'vue'
import { buildPieSlices } from '@/utils/pieChart'
import ItemTypePieChart from '@/components/ItemTypePieChart.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  size: { type: Number, default: 44 },
  maxSlices: { type: Number, default: 6 },
  showLegend: { type: Boolean, default: true },
  fill: { type: Boolean, default: false },
  expandable: { type: Boolean, default: true },
  title: { type: String, default: '' },
})

const chartKey = ref(0)
watch(
  () => [props.items, props.maxSlices, props.size],
  () => {
    chartKey.value += 1
  },
  { deep: true },
)

const uid = `mini-${Math.random().toString(36).slice(2, 9)}`

const normalizedItems = computed(() =>
  (props.items || []).map((item) => ({
    ...item,
    name: item.name || item.reason || '未标注',
    count: item.count || 0,
  })),
)

const slices = computed(() =>
  buildPieSlices(normalizedItems.value, {
    maxSlices: props.maxSlices,
    mergeOther: true,
  }),
)

const groupStyle = computed(() => {
  const chartCol = `${props.size + 4}px`
  const pctCol = '38px'
  if (props.fill && props.showLegend) {
    return {
      gridTemplateColumns: `${chartCol} minmax(0, 1fr) ${pctCol}`,
      width: '100%',
    }
  }
  if (props.showLegend) {
    const width = props.size + 4 + 148 + 38 + 12
    return {
      gridTemplateColumns: `${chartCol} minmax(0, 1fr) ${pctCol}`,
      width: `${width}px`,
    }
  }
  return { width: 'auto' }
})

const activeIndex = ref(-1)
const dialogVisible = ref(false)

const grandTotal = computed(() =>
  normalizedItems.value.reduce((sum, item) => sum + (item.count || 0), 0),
)

const dialogTitle = computed(() =>
  props.title ? `${props.title} · 不合格原因占比` : '不合格原因占比',
)

function openExpand() {
  if (props.expandable && slices.value.length) {
    dialogVisible.value = true
  }
}

function sliceStyle(index) {
  return { '--slice-delay': `${index * 0.04}s` }
}
</script>

<template>
  <template v-if="slices.length">
    <div
      class="mini-pie-row"
      :class="{
        'mini-pie-row--chart-only': !showLegend,
        'mini-pie-row--fill': fill && showLegend,
        'mini-pie-row--expandable': expandable,
      }"
      :title="expandable ? '点击查看大图' : undefined"
      @click="openExpand"
    >
    <div class="mini-pie-group" :style="groupStyle">
      <div
        class="mini-pie-wrap"
        :style="{ width: `${size}px`, height: `${size}px` }"
      >
        <svg
          :key="chartKey"
          class="mini-pie-svg"
          viewBox="0 0 200 200"
          role="img"
          :aria-label="`违规原因占比：${slices.map((s) => `${s.name} ${s.share}%`).join('，')}`"
        >
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
              <stop offset="45%" :stop-color="slice.gradient[1]" stop-opacity="0.8" />
              <stop offset="100%" :stop-color="slice.gradient[2]" stop-opacity="0.58" />
            </linearGradient>
          </defs>

          <g class="mini-pie-slices">
            <path
              v-for="(slice, index) in slices"
              :key="slice.name"
              class="mini-pie-slice"
              :class="{ 'mini-pie-slice--active': activeIndex === index }"
              :d="slice.path"
              :fill="`url(#${uid}-grad-${index})`"
              :style="sliceStyle(index)"
              @mouseenter="activeIndex = index"
              @mouseleave="activeIndex = -1"
            />
          </g>
        </svg>
      </div>

      <ul v-if="showLegend" class="mini-pie-labels">
        <li
          v-for="(slice, index) in slices"
          :key="slice.name"
          class="mini-pie-labels__item"
          :class="{ 'mini-pie-labels__item--active': activeIndex === index }"
          @mouseenter="activeIndex = index"
          @mouseleave="activeIndex = -1"
        >
          <span
            class="mini-pie-labels__dot"
            :style="{
              background: `linear-gradient(135deg, ${slice.gradient[0]}, ${slice.gradient[1]})`,
            }"
          />
          <span class="mini-pie-labels__name" :title="slice.name">{{ slice.name }}</span>
        </li>
      </ul>
      <ul v-if="showLegend" class="mini-pie-pcts">
        <li v-for="slice in slices" :key="slice.name" class="mini-pie-pcts__item">
          {{ slice.share }}%
        </li>
      </ul>
    </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="min(720px, 92vw)"
      class="mini-pie-dialog"
      append-to-body
      destroy-on-close
    >
      <ItemTypePieChart
        :items="normalizedItems"
        :grand-total="grandTotal"
        center-label="不合格项次"
        count-unit="次"
        :max-slices="12"
      />
    </el-dialog>
  </template>
  <span v-else class="mini-pie-empty">-</span>
</template>

<style scoped>
.mini-pie-row {
  display: inline-flex;
  justify-content: flex-start;
  width: auto;
  max-width: 100%;
  padding: 2px 0;
  min-width: 0;
}

.mini-pie-row--expandable {
  cursor: zoom-in;
  border-radius: 6px;
  transition: background 0.15s ease;
}

.mini-pie-row--expandable:hover {
  background: rgba(107, 140, 255, 0.06);
}

.mini-pie-row--fill {
  display: flex;
  width: 100%;
}

.mini-pie-row--chart-only {
  justify-content: center;
}

.mini-pie-row--chart-only .mini-pie-group {
  display: block;
  width: auto;
}

.mini-pie-group {
  display: grid;
  align-items: center;
  column-gap: 6px;
  max-width: 100%;
  min-width: 0;
}

.mini-pie-wrap {
  position: relative;
  flex-shrink: 0;
  justify-self: start;
  filter: drop-shadow(0 4px 10px rgba(59, 100, 200, 0.12));
}

.mini-pie-svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.mini-pie-slice {
  opacity: 0;
  transform-origin: 100px 100px;
  stroke: rgba(255, 255, 255, 0.42);
  stroke-width: 0.5;
  animation: miniSliceIn 0.75s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  animation-delay: var(--slice-delay, 0s);
  transition: opacity 0.2s ease, transform 0.2s ease;
  cursor: default;
}

.mini-pie-slice--active {
  opacity: 1 !important;
  transform: scale(1.04);
}

.mini-pie-labels {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.mini-pie-labels__item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  line-height: 1.3;
  min-height: 16px;
  border-radius: 4px;
  transition: background 0.15s ease;
}

.mini-pie-labels__item--active {
  background: rgba(107, 140, 255, 0.07);
}

.mini-pie-labels__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.65);
}

.mini-pie-labels__name {
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-pie-pcts {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
  justify-self: end;
}

.mini-pie-pcts__item {
  color: #64748b;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  line-height: 1.3;
  min-height: 16px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.mini-pie-empty {
  color: #94a3b8;
  font-size: 12px;
}

@keyframes miniSliceIn {
  0% {
    opacity: 0;
    transform: scale(0.88);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>

<style>
.mini-pie-dialog .el-dialog__body {
  padding-top: 8px;
}
</style>
